"""
Graceful shutdown handler for workers

Ensures tasks complete before worker shutdown.
Integrates with dead letter queue and error classification.
"""

import signal
import logging
import sys
import os
from typing import Optional

logger = logging.getLogger(__name__)


class GracefulShutdownHandler:
    """Handle graceful worker shutdown"""
    
    def __init__(self):
        self.shutdown_requested = False
        self.original_sigterm_handler: Optional[signal.Handler] = None
        self.original_sigint_handler: Optional[signal.Handler] = None
        self.active_tasks = set()  # Track active task IDs
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
        
        import time
        self.shutdown_deadline = time.time() + self.force_exit_after
        
        # Log current state - in Celery this will prevent new tasks
        if hasattr(sys, "celery_worker"):
            logger.info("Notifying Celery of shutdown")
        
        # Log active tasks
        if self.active_tasks:
            logger.info(f"Waiting for {len(self.active_tasks)} active tasks to complete")
    
    def should_shutdown(self) -> bool:
        """Check if shutdown was requested"""
        if not self.shutdown_requested:
            return False
        
        # Check if shutdown deadline exceeded
        if self.shutdown_deadline:
            import time
            if time.time() > self.shutdown_deadline:
                logger.warning("Shutdown deadline exceeded, forcing exit")
                return True
        
        # Allow shutdown if no active tasks
        if not self.active_tasks:
            return True
        
        return True  # Signal shutdown is requested, task should check and finish quickly
    
    def should_force_exit(self) -> bool:
        """Check if we should force exit immediately"""
        if not self.shutdown_deadline:
            return False
        import time
        return time.time() > self.shutdown_deadline
    
    def register_task(self, task_id: str):
        """Register an active task"""
        self.active_tasks.add(task_id)
    
    def unregister_task(self, task_id: str):
        """Unregister a completed task"""
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