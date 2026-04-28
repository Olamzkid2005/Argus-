"""
Standardized error boundary for Celery tasks.

Provides a context manager that wraps task execution with consistent
error classification, logging, dead-letter queue integration, and
engagement state transitions.

Usage:
    from tasks.base import task_error_boundary
    
    @app.task(bind=True)
    def my_task(self, engagement_id):
        with task_error_boundary(self, engagement_id, "my_phase"):
            # Task logic here
            ...

Stolen from: Shannon's two-layer architecture pattern (thin orchestration + service boundary)
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)


@contextmanager
def task_error_boundary(
    task,
    engagement_id: str,
    phase_name: str,
    db_conn_string: Optional[str] = None,
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
    try:
        yield
    except Exception as e:
        # 1. Classify the error
        from error_classifier import classify_error_with_code, log_classified_error

        classification = classify_error_with_code(
            e,
            task_name=getattr(task, "name", str(task)),
            retry_count=getattr(task.request, "retries", 0) if hasattr(task, "request") else 0,
        )

        # 2. Log with full classification
        log_classified_error(
            classification=classification,
            task_id=getattr(task.request, "id", "unknown") if hasattr(task, "request") else "unknown",
            task_name=getattr(task, "name", str(task)),
            error=e,
            extra_context={"engagement_id": engagement_id, "phase": phase_name},
        )

        # 3. Send non-retryable errors to dead-letter queue
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

        # 4. Transition engagement to failed (skip if already terminal)
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

        # 5. Re-raise the original exception
        raise
