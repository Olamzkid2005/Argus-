"""
Standardized error boundary for Celery tasks.

Provides a context manager that wraps task execution with consistent
error classification, logging, dead-letter queue integration, and
engagement state transitions.

Usage:
    from tasks.base import task_context, task_error_boundary

    @app.task(bind=True)
    def my_task(self, engagement_id):
        with task_context(self, engagement_id, "my_phase") as ctx:
            result = ctx.orchestrator.run_xxx(ctx.job)
            ...

Stolen from: Shannon's two-layer architecture pattern (thin orchestration + service boundary)
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

# Celery's SoftTimeLimitExceeded is raised when a task exceeds its soft time limit.
# We catch it here to transition the engagement to 'failed' with a clear message,
# rather than leaving it stuck in an intermediate state.
try:
    from billiard.exceptions import SoftTimeLimitExceeded
except ImportError:
    SoftTimeLimitExceeded = None

logger = logging.getLogger(__name__)


@dataclass
class TaskContext:
    """Encapsulates all the scaffolding a task needs."""

    engagement_id: str
    job_type: str
    job: dict
    trace_id: str
    orchestrator: Any = None
    db_conn_string: str = ""
    redis_url: str = ""


@contextmanager
def task_context(
    task,
    engagement_id: str,
    job_type: str,
    job_extra: dict = None,
    trace_id: str = None,
    current_state: str = None,
):
    """
    Unified task scaffolding context manager.

    Handles:
    1. DATABASE_URL / REDIS_URL resolution
    2. TracingManager init and trace_id generation
    3. DistributedLock acquisition
    4. EngagementStateMachine init and initial transition
    5. Orchestrator init
    6. Error handling with state transition to 'failed'

    Yields:
        TaskContext with .orchestrator, .job, .trace_id

    Usage:
        with task_context(self, id, "recon",
                          job_extra={"target": target, "budget": budget},
                          current_state="created") as ctx:
            result = ctx.orchestrator.run_recon(ctx.job)
            ctx.state.transition("scanning", "...")
    """
    from distributed_lock import DistributedLock, LockContext
    from orchestrator import Orchestrator
    from state_machine import EngagementStateMachine
    from tracing import TracingManager
    from utils.logging_utils import ScanLogger

    slog = ScanLogger(job_type, engagement_id=engagement_id)

    db_conn_string = os.getenv("DATABASE_URL")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

    tracing_manager = TracingManager(db_conn_string)
    if not trace_id:
        trace_id = tracing_manager.generate_trace_id()

    ctx = TaskContext(
        engagement_id=engagement_id,
        job_type=job_type,
        job={
            "type": job_type,
            "engagement_id": engagement_id,
            "trace_id": trace_id,
            **(job_extra or {}),
        },
        trace_id=trace_id,
        db_conn_string=db_conn_string,
        redis_url=redis_url,
    )

    slog.phase_start(job_type, target=(job_extra or {}).get("target", ""))

    with tracing_manager.trace_execution(engagement_id, job_type, trace_id):
        lock = DistributedLock(redis_url)
        _lock_acquired = False
        try:
            with LockContext(lock, engagement_id):
                _lock_acquired = True
                sm = EngagementStateMachine(
                    engagement_id,
                    db_connection_string=db_conn_string,
                    current_state=current_state or _get_engagement_state(engagement_id, db_conn_string),
                )
                from websocket_events import get_websocket_publisher
                sm._ws_publisher = get_websocket_publisher()
                ctx.state = sm

                slog.info(f"Lock acquired, state machine initialized")

                orchestrator = Orchestrator(engagement_id, trace_id=trace_id)
                ctx.orchestrator = orchestrator

                yield ctx
        except SoftTimeLimitExceeded as ste:
            slog.error(f"Soft time limit exceeded — transitioning to failed")
            logger.warning(
                "Soft time limit exceeded for %s engagement %s — transitioning to failed",
                job_type, engagement_id,
            )
            if _lock_acquired:
                try:
                    current = _get_engagement_state(engagement_id, db_conn_string)
                    if current not in ("complete", "failed"):
                        sm = EngagementStateMachine(
                            engagement_id,
                            db_connection_string=db_conn_string,
                            current_state=current,
                        )
                        sm.transition("failed", f"{job_type} timed out (soft time limit exceeded)")
                        slog.phase_complete(job_type, status="failed", reason="soft_time_limit")
                        task._failed_transition_done = True
                except Exception as st_error:
                    logger.error("Failed to transition on soft time limit: %s", st_error)
            raise
        except Exception as e:
            slog.error(f"Task failed: {e}")
            if _lock_acquired:
                current = _get_engagement_state(engagement_id, db_conn_string)
                if current not in ("complete", "failed"):
                    try:
                        sm = EngagementStateMachine(
                            engagement_id,
                            db_connection_string=db_conn_string,
                            current_state=current,
                        )
                        sm.transition("failed", f"{job_type} failed: {e}")
                        slog.phase_complete(job_type, status="failed", reason=str(e)[:100])
                        task._failed_transition_done = True
                    except Exception as sm_error:
                        logger.error("State transition to failed error: %s", sm_error)
            raise


@contextmanager
def task_error_boundary(
    task,
    engagement_id: str,
    phase_name: str,
    db_conn_string: str | None = None,
):
    """Standardized error boundary for Celery tasks.

    Wraps task execution with:
    1. Error classification via ErrorCode / classify_error_with_code
    2. Structured logging of the classified error
    3. Dead-letter queue integration for non-retryable failures
    4. Engagement state transition to "failed" on unrecoverable errors

    Args:
        task: The Celery task instance (self from bind=True tasks).
        engagement_id: Engagement ID for state transitions.
        phase_name: Human-readable phase name for error messages.
        db_conn_string: Database connection string. Auto-resolves if not provided.

    Yields:
        None — wraps the task body.

    Raises:
        The original exception after classification and logging.
    """
    from utils.logging_utils import ScanLogger
    slog = ScanLogger(phase_name, engagement_id=engagement_id)

    try:
        yield
    except SoftTimeLimitExceeded as ste:
        slog.error(f"Soft time limit exceeded in {phase_name}")
        logger.warning(
            "Soft time limit exceeded in %s for engagement %s — transitioning to failed",
            phase_name, engagement_id,
        )
        try:
            from database.connection import db_cursor
            with db_cursor() as cursor:
                cursor.execute("SELECT status FROM engagements WHERE id = %s", (engagement_id,))
                row = cursor.fetchone()
                current_state = row[0] if row else "created"
            if current_state not in ("complete", "failed"):
                from state_machine import EngagementStateMachine
                sm = EngagementStateMachine(engagement_id, current_state=current_state)
                sm.transition("failed", f"{phase_name} timed out (soft time limit exceeded)")
        except Exception as state_error:
            logger.error("Failed to update engagement state on soft time limit: %s", state_error)
        raise
    except Exception as e:
        slog.error(f"{phase_name} failed: {e}")
        from error_classifier import classify_error_with_code, log_classified_error

        classification = classify_error_with_code(
            e,
            task_name=getattr(task, "name", str(task)),
            retry_count=getattr(task.request, "retries", 0) if hasattr(task, "request") else 0,
        )

        log_classified_error(
            classification=classification,
            task_id=getattr(task.request, "id", "unknown") if hasattr(task, "request") else "unknown",
            task_name=getattr(task, "name", str(task)),
            error=e,
            extra_context={"engagement_id": engagement_id, "phase": phase_name},
        )

        if not classification.should_retry:
            try:
                from dead_letter_queue import get_dlq
                dlq = get_dlq()
                dlq.enqueue(
                    task_id=getattr(task.request, "id", "unknown") if hasattr(task, "request") else "unknown",
                    task_name=getattr(task, "name", str(task)),
                    args=list(getattr(task.request, "args", [])),
                    kwargs=getattr(task.request, "kwargs", {}),
                    error_message=str(e),
                    error_class=type(e).__name__,
                    retry_count=getattr(task.request, "retries", 0) if hasattr(task, "request") else 0,
                    engagement_id=engagement_id,
                )
            except Exception as dlq_error:
                logger.error("Failed to enqueue to DLQ: %s", dlq_error)

        try:
            from database.connection import db_cursor
            with db_cursor() as cursor:
                cursor.execute(
                    "SELECT status FROM engagements WHERE id = %s",
                    (engagement_id,),
                )
                row = cursor.fetchone()
                current_state = row[0] if row else "created"

            if current_state not in ("complete", "failed"):
                from state_machine import EngagementStateMachine
                sm = EngagementStateMachine(
                    engagement_id,
                    current_state=current_state,
                )
                sm.transition("failed", f"{phase_name} failed: {classification.category.value}: {e}")
        except Exception as state_error:
            logger.error("Failed to update engagement state after error: %s", state_error)

        raise


def _get_engagement_state(engagement_id: str, db_conn_string: str = None) -> str:
    """Query the current engagement state from the database."""
    if not db_conn_string:
        db_conn_string = os.getenv("DATABASE_URL")
    try:
        from database.connection import connect
        from utils.validation import validate_uuid
        valid_id = validate_uuid(engagement_id, "engagement_id")
        conn = connect(db_conn_string)
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM engagements WHERE id = %s", (valid_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return row[0] if row else "created"
    except Exception:
        return "created"
