"""
Shared Redis configuration for Argus workers.

Single source of truth for REDIS_URL so that celery_app.py,
dead_letter_queue.py, and any other Redis consumer stay in sync.
"""

import logging
import os

logger = logging.getLogger(__name__)

_REDIS_URL: str | None = None


def get_redis_url() -> str:
    global _REDIS_URL
    if _REDIS_URL is not None:
        return _REDIS_URL
    url = os.getenv("REDIS_URL")
    if url:
        _REDIS_URL = url
        return _REDIS_URL
    _REDIS_URL = "redis://localhost:6379"
    logger.warning(
        "REDIS_URL not set — defaulting to redis://localhost:6379. "
        "Set REDIS_URL environment variable for production use."
    )
    return _REDIS_URL


REDIS_URL = get_redis_url()
