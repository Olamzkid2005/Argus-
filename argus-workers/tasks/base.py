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
# Use the real Celery exception for reliable isinstance checks.
try:
    from celery.exceptions import SoftTimeLimitExceeded as _SoftTimeLimitExceeded
except ImportError:
    try:
        from billiard.exceptions import SoftTimeLimitExceeded as _SoftTimeLimitExceeded
    except ImportError:
        # Neither library available — create a dummy so the except clause
        # in task_context doesn't raise TypeError on None.
        class _SoftTimeLimitExceeded(Exception):  # type: ignore
            pass

# Public alias for use in except clauses throughout this module.
# We also check by class name as a final fallback (see _is_soft_timeout).
SoftTimeLimitExceeded = _SoftTimeLimitExceeded


def _is_soft_timeout(exc: BaseException) -> bool:
    """Check if *exc* is a soft time limit exceeded signal.

    First tries isinstance against the known class, then falls back to
    matching the class name so we never miss a timeout even when the
    import chain above produced a dummy type.
    """
    if isinstance(exc, _SoftTimeLimitExceeded):
        return True
    return "SoftTimeLimitExceeded" in type(exc).__name__

logger = logging.getLogger(__name__)


def _transition_to_failed_on_timeout(
    task, ctx, sm, engagement_id: str, job_type: str,
    _lock_acquired: bool, _state_assigned: bool, slog,
) -> None:
    """Shared helper: transition engagement to 'failed' on soft time limit."""
    if _lock_acquired:
        try:
            from tasks.utils import get_engagement_state as _ges
            from database.connection import get_db as _get_db
            current = sm.current_state if _state_assigned else _ges(engagement_id, os.getenv("DATABASE_URL"))
            if current not in ("complete", "failed"):
                if _state_assigned:
                    ctx.state.transition("failed", f"{job_type} timed out (soft time limit exceeded)")
                else:
                    sm.transition("failed", f"{job_type} timed out (soft time limit exceeded)")
                slog.phase_complete(job_type, status="failed", reason="soft_time_limit")
                # Prevent double-transition by Celery's on_failure hook
                # and any outer task_error_boundary.
                task._failed_transition_done = True
        except Exception as st_error:
            logger.error("Failed to transition on soft time limit: %s", st_error)


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
    from distributed_lock import DistributedLock, LockAcquisitionError, LockContext
    from feature_flags import is_enabled as _ff_enabled
    from orchestrator import Orchestrator
    from runtime import EngagementState, shadow_compare
    from state_machine import EngagementStateMachine
    from tasks.utils import get_engagement_state
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
        _state_assigned = False
        try:
            with LockContext(lock, engagement_id):
                _lock_acquired = True
                sm = EngagementStateMachine(
                    engagement_id,
                    db_connection_string=db_conn_string,
                    current_state=current_state or get_engagement_state(engagement_id, db_conn_string),
                )
                from websocket_events import get_websocket_publisher
                sm._ws_publisher = get_websocket_publisher()

                # Phase 1: Wrap state machine in canonical EngagementState
                # when feature flag is enabled.
                if _ff_enabled("ENGAGEMENT_STATE", default=False):
                    state = EngagementState(engagement_id, state_machine=sm)
                    # Shadow-compare: new EngagementState vs raw state machine
                    shadow_compare(
                        "engagement_state", engagement_id,
                        new_result=state.to_dict(),
                        old_path_fn=lambda sm=sm: {
                            "current_state": sm.current_state,
                            "engagement_id": sm.engagement_id,
                        },
                        key_fields=["current_state", "engagement_id"],
                    )
                else:
                    state = sm
                _state_assigned = True
                ctx.state = state

                slog.info("Lock acquired, state machine initialized")

                orchestrator = Orchestrator(engagement_id, trace_id=trace_id)
                orchestrator.state = state  # Always wire state into orchestrator (regardless of type)
                ctx.orchestrator = orchestrator

                yield ctx
        except SoftTimeLimitExceeded:
            slog.error("Soft time limit exceeded — transitioning to failed")
            logger.warning(
                "Soft time limit exceeded for %s engagement %s — transitioning to failed",
                job_type, engagement_id,
            )
            _transition_to_failed_on_timeout(task, ctx, sm, engagement_id, job_type,
                                             _lock_acquired, _state_assigned, slog)
            raise
        except LockAcquisitionError:
            # Lock contention is transient — don't mark engagement as failed.
            # Let Celery retry the task instead.
            slog.warning("Lock acquisition failed for %s — will retry", engagement_id)
            raise
        except Exception as e:
            # Catch SoftTimeLimitExceeded by name in case the imported class
            # is a dummy that doesn't match the real exception type at runtime.
            if _is_soft_timeout(e):
                slog.error("Soft time limit exceeded (name-matched) — transitioning to failed")
                _transition_to_failed_on_timeout(task, ctx, sm, engagement_id, job_type,
                                                 _lock_acquired, _state_assigned, slog)
                raise

            # If a nested task_error_boundary already transitioned us to failed,
            # skip the duplicate transition (bug #8 fix).
            if getattr(task, '_failed_transition_done', False):
                logger.warning(
                    "Task %s already has _failed_transition_done set — "
                    "skipping duplicate failed transition for %s",
                    task.request.id if hasattr(task, 'request') else '?',
                    engagement_id,
                )
                raise

            logger.error("Task failed for %s engagement %s: %s", job_type, engagement_id, e)
            if _lock_acquired:
                try:
                    current = sm.current_state if _state_assigned else get_engagement_state(engagement_id, db_conn_string)
                    if current not in ("complete", "failed"):
                        if _state_assigned:
                            ctx.state.transition("failed", f"{job_type} failed: {e}")
                        else:
                            sm.transition("failed", f"{job_type} failed: {e}")
                        slog.phase_complete(job_type, status="failed", reason=str(e)[:100])
                        # Mark transition as done to prevent double-transition
                        # in the Celery task's BaseTask.on_failure hook AND
                        # in any outer task_error_boundary.
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
    """Standardized error boundary for Celery tasks — SECONDARY handler.

    H-03: This is a secondary error boundary. It handles:
    1. Error classification via ErrorCode / classify_error_with_code
    2. Structured logging of the classified error
    3. Dead-letter queue integration for non-retryable failures

    IMPORTANT: This boundary does NOT transition engagement state to 'failed'.
    State transitions are the sole responsibility of task_context() — the
    single authoritative error handler. If task_context() is not wrapping
    this call, ensure the caller handles state transitions separately.

    Args:
        task: The Celery task instance (self from bind=True tasks).
        engagement_id: Engagement ID (for logging/DLQ context).
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
    except SoftTimeLimitExceeded:
        slog.error("Soft time limit exceeded in %s", phase_name)
        logger.warning(
            "Soft time limit exceeded in %s for engagement %s — "
            "state transition handled by task_context if present",
            phase_name, engagement_id,
        )
        raise
    except Exception as e:
        # Check by name too (see task_context for why)
        if _is_soft_timeout(e):
            slog.error("Soft time limit exceeded (name-matched) in %s", phase_name)
            raise

        from error_classifier import classify_error_with_code
        classification = classify_error_with_code(e)

        slog.error(
            "%s failed: %s [%s]",
            phase_name, e, classification.error_code.name if classification else "UNKNOWN",
        )

        # Send to DLQ when non-retryable
        if classification and not classification.should_retry:
            try:
                dlq = get_dlq()
                dlq.enqueue(
                    task_id="unknown",
                    task_name=phase_name,
                    args=[engagement_id],
                    kwargs={},
                    error_message=str(e),
                    error_class=type(e).__name__,
                    retry_count=0,
                    engagement_id=engagement_id,
                )
            except Exception as dlq_error:
                logger.error("Failed to enqueue DLQ message: %s", dlq_error)
        raise
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
        # If an outer task_context already handled this, skip.
        if getattr(task, '_failed_transition_done', False):
            raise

        slog.error("%s failed: %s", phase_name, e)
        from error_classifier import classify_error_with_code, log_classified_error

        classification = classify_error_with_code(
            e,
            task_name=getattr(task, "name", str(task)),
            retry_count=getattr(task.request, "retries", 0) if hasattr(task, "request") else 0,
        )

        # Store classification on task so on_retry can use retry_delay_seconds
        task._last_classification = classification

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


