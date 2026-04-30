"""
Task utilities - Shared helpers for Celery tasks.

Provides Redis-based ReconContext persistence across the recon → scan
Celery task boundary.
"""
import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

RECON_CONTEXT_KEY = "recon_context:{engagement_id}"
RECON_CONTEXT_TTL = 3600  # 1 hour


def save_recon_context(engagement_id: str, ctx, redis_url: str = None):
    """
    Save a ReconContext to Redis for cross-task access.

    Args:
        engagement_id: Engagement UUID
        ctx: ReconContext instance (must have to_dict() method)
        redis_url: Redis URL
    """
    import redis as redis_module
    r = redis_module.from_url(redis_url or os.getenv("REDIS_URL", "redis://localhost:6379"))
    key = RECON_CONTEXT_KEY.format(engagement_id=engagement_id)
    r.setex(key, RECON_CONTEXT_TTL, json.dumps(ctx.to_dict() if hasattr(ctx, "to_dict") else ctx.__dict__))


def load_recon_context(engagement_id: str, redis_url: str = None) -> Optional[object]:
    """
    Load a ReconContext from Redis.

    Args:
        engagement_id: Engagement UUID
        redis_url: Redis URL

    Returns:
        ReconContext instance or None
    """
    import redis as redis_module
    from models.recon_context import ReconContext

    r = redis_module.from_url(redis_url or os.getenv("REDIS_URL", "redis://localhost:6379"))
    key = RECON_CONTEXT_KEY.format(engagement_id=engagement_id)
    raw = r.get(key)
    if not raw:
        return None
    data = json.loads(raw)
    return ReconContext.from_dict(data)
