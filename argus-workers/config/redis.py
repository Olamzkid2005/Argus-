"""
Shared Redis configuration for Argus workers.

Single source of truth for REDIS_URL so that celery_app.py,
dead_letter_queue.py, and any other Redis consumer stay in sync.
"""

import logging
import os

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL")
if not REDIS_URL:
    REDIS_URL = "redis://localhost:6379"
    logger.warning(
        "REDIS_URL not set — defaulting to %s. "
        "Set REDIS_URL environment variable for production use.",
        REDIS_URL,
    )
