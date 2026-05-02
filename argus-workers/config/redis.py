"""
Shared Redis configuration for Argus workers.

Single source of truth for REDIS_URL so that celery_app.py,
dead_letter_queue.py, and any other Redis consumer stay in sync.
"""

import os

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
