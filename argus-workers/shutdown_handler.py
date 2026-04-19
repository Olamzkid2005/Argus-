"""
Graceful shutdown handler for workers

Ensures tasks complete before worker shutdown
"""

import signal
import logging
import sys
from typing import Optional

logger = logging.getLogger(__name__)


class GracefulShutdownHandler:
    """Handle graceful worker shutdown"""
    
    def __init__(self):
        self.shutdown_requested = False
        self.original_sigterm_handler: Optional[signal.Handler] = None
        self.original_sigint_handler: Optional[signal.Handler] = None
    
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
        
        # Log current state - in Celery this will prevent new tasks
        if hasattr(sys, "celery_worker"):
            logger.info("Notifying Celery of shutdown")
    
    def should_shutdown(self) -> bool:
        """Check if shutdown was requested"""
        return self.shutdown_requested
    
    def restore(self):
        """Restore original signal handlers"""
        if self.original_sigterm_handler:
            signal.signal(signal.SIGTERM, self.original_sigterm_handler)
        if self.original_sigint_handler:
            signal.signal(signal.SIGINT, self.original_sigint_handler)


# Global shutdown handler
shutdown_handler = GracefulShutdownHandler()


def setup_graceful_shutdown():
    """Setup graceful shutdown"""
    shutdown_handler.setup()


def should_graceful_shutdown() -> bool:
    """Check if should gracefully shutdown"""
    return shutdown_handler.should_shutdown()