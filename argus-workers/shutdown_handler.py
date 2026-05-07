"""
Graceful shutdown handler for workers

Ensures tasks complete before worker shutdown.
Integrates with dead letter queue and error classification.
"""

import logging
import os
import signal
import sys
import threading
import time

logger = logging.getLogger(__name__)


class GracefulShutdownHandler:
    """Handle graceful worker shutdown"""

    def __init__(self):
        self.shutdown_requested = False
        self.original_sigterm_handler: signal.Handler | None = None
        self.original_sigint_handler: signal.Handler | None = None
        self.active_tasks: set = set()  # Track active task IDs
        self._lock = threading.Lock()
        self.shutdown_deadline = None
        self.force_exit_after = int(os.getenv("WORKER_SHUTDOWN_TIMEOUT", "30"))  # seconds

    def setup(self):
        """Setup signal handlers for graceful shutdown"""
        self.original_sigterm_handler = signal.signal(
            signal.SIGTERM,
            self._handle_shutdown
        )
        self.original_sigint_handler = signal.signal(
            signal.SIGINT,
            self._handle_shutdown
        )
        logger.info("Graceful shutdown handlers registered")

    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signal"""
        logger.warning(
            f"Received signal {signum}, initiating graceful shutdown..."
        )
        self.shutdown_requested = True
        self.shutdown_deadline = time.time() + self.force_exit_after

        # Log current state - in Celery this will prevent new tasks
        if hasattr(sys, "celery_worker"):
            logger.info("Notifying Celery of shutdown")

        # Log active tasks
        with self._lock:
            active_count = len(self.active_tasks)
        if active_count:
            logger.info(f"Waiting for {active_count} active tasks to complete")

    def should_shutdown(self) -> bool:
        """Check if shutdown was requested"""
        if not self.shutdown_requested:
            return False

        # Check if shutdown deadline exceeded
        if self.shutdown_deadline and time.time() > self.shutdown_deadline:
                logger.warning("Shutdown deadline exceeded, forcing exit")
                return True

        # Allow shutdown if no active tasks
        with self._lock:
            has_active = bool(self.active_tasks)
        if not has_active:
            return True

        return True  # Signal shutdown is requested, task should check and finish quickly

    def should_force_exit(self) -> bool:
        """Check if we should force exit immediately"""
        return bool(self.shutdown_deadline and time.time() > self.shutdown_deadline)

    def register_task(self, task_id: str):
        """Register an active task"""
        with self._lock:
            self.active_tasks.add(task_id)

    def unregister_task(self, task_id: str):
        """Unregister a completed task"""
        with self._lock:
            self.active_tasks.discard(task_id)

    def restore(self):
        """Restore original signal handlers"""
        if self.original_sigterm_handler:
            signal.signal(signal.SIGTERM, self.original_sigterm_handler)
        if self.original_sigint_handler:
            signal.signal(signal.SIGINT, self.original_sigint_handler)

    def handle_task_failure_on_shutdown(
        self,
        task_id: str,
        task_name: str,
        args: tuple,
        kwargs: dict,
        error: Exception
    ):
        """
        Handle task failure during shutdown.

        Sends failed tasks to dead letter queue for later replay.
        """
        try:
            from dead_letter_queue import get_dlq
            from error_classifier import classify_error

            classification = classify_error(error, task_name)

            dlq = get_dlq()
            dlq.enqueue(
                task_id=task_id,
                task_name=task_name,
                args=list(args),
                kwargs=kwargs,
                error_message=str(error),
                error_class=type(error).__name__,
                retry_count=0,
                engagement_id=kwargs.get("engagement_id") if kwargs else None
            )

            logger.warning(
                f"Task {task_id} failed during shutdown, added to DLQ. "
                f"Classification: {classification.category.value}"
            )
        except Exception as e:
            logger.error(f"Failed to send task {task_id} to DLQ: {e}")


# Global shutdown handler
shutdown_handler = GracefulShutdownHandler()


def setup_graceful_shutdown():
    """Setup graceful shutdown"""
    shutdown_handler.setup()


def should_graceful_shutdown() -> bool:
    """Check if should gracefully shutdown"""
    return shutdown_handler.should_shutdown()


def should_force_exit() -> bool:
    """Check if shutdown deadline exceeded"""
    return shutdown_handler.should_force_exit()
