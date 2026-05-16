"""
Task utilities - Shared helpers for Celery tasks.

Provides:
- Redis-based ReconContext persistence across the recon → scan boundary
- LlmCostTracker for per-engagement LLM budget tracking
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

RECON_CONTEXT_KEY = "recon_context:{engagement_id}"
RECON_CONTEXT_TTL = 7200  # 2 hours (was 1h — scan can take 60min to execute)
LLM_COST_KEY = "llm_cost:{engagement_id}"


class LlmCostTracker:
    """Tracks LLM spend per engagement against a budget.

    Uses Redis INCRBYFLOAT for cross-worker tracking.
    Falls back to in-process counter if Redis is unavailable.

    Args:
        engagement_id: Engagement UUID
        max_cost: Maximum LLM spend in USD (default 0.50)
    """

    def __init__(self, engagement_id: str, max_cost: float = 0.50):
        self.engagement_id = engagement_id
        self.max_cost = max_cost
        self._local_spend = 0.0
        self._redis_key = LLM_COST_KEY.format(engagement_id=engagement_id)
        self._redis = None
        try:
            import redis as redis_module
            self._redis = redis_module.from_url(
                os.getenv("REDIS_URL", "redis://localhost:6379"),
                socket_connect_timeout=2,
                socket_timeout=2,
            )
        except Exception:
            logger.warning("Redis unavailable for LlmCostTracker — cost cap disabled for %s", engagement_id)

    def has_remaining_budget(self) -> bool:
        """Check if we're still within budget.

        Returns:
            True if total cost is less than max_cost
        """
        return self._get_current_cost() < self.max_cost

    def record_llm_call(self, cost: float) -> bool:
        """Record an LLM call cost.

        Args:
            cost: Cost in USD

        Returns:
            True if still within budget after recording
        """
        self._local_spend += cost
        if self._redis:
            try:
                self._redis.incrbyfloat(self._redis_key, cost)
                self._redis.expire(self._redis_key, 86400)  # 24h TTL
            except Exception:
                logger.warning("Failed to record LLM cost in Redis for %s", self.engagement_id)
        return self._get_current_cost() < self.max_cost

    def _get_current_cost(self) -> float:
        """Get total cost spent so far (max of local + Redis).

        Returns:
            Total cost in USD
        """
        if self._redis:
            try:
                redis_cost = float(self._redis.get(self._redis_key) or 0)
                return max(self._local_spend, redis_cost)
            except Exception:
                pass
        return self._local_spend


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
    try:
        key = RECON_CONTEXT_KEY.format(engagement_id=engagement_id)
        r.setex(key, RECON_CONTEXT_TTL, json.dumps(ctx.to_dict() if hasattr(ctx, "to_dict") else ctx.__dict__))
    finally:
        r.close()


def load_recon_context(engagement_id: str, redis_url: str = None) -> object | None:
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
    try:
        key = RECON_CONTEXT_KEY.format(engagement_id=engagement_id)
        raw = r.get(key)
        if not raw:
            return None
        data = json.loads(raw)
        return ReconContext.from_dict(data)
    finally:
        r.close()


def fetch_engagement_scan_options(engagement_id: str) -> dict[str, str | bool]:
    """
    Read scan-related flags from engagements for downstream tasks.

    Used when Celery was invoked without full job payload (e.g. expand_recon → scan).
    """
    defaults: dict[str, str | bool] = {
        "scan_mode": "agent",
        "aggressiveness": "default",
        "agent_mode": True,
        "bug_bounty_mode": False,
    }
    try:
        from database.connection import db_cursor
        from utils.validation import validate_uuid

        eid = validate_uuid(engagement_id, "engagement_id")
        with db_cursor() as cursor:
            cursor.execute(
                """
                SELECT scan_mode, scan_aggressiveness, agent_mode, bug_bounty_mode
                FROM engagements WHERE id = %s
                """,
                (eid,),
            )
            row = cursor.fetchone()
            if row:
                sm, sa, am, bbm = row[0], row[1], row[2], row[3]
                return {
                    "scan_mode": (sm or defaults["scan_mode"]) if isinstance(sm, str) else defaults["scan_mode"],
                    "aggressiveness": (sa or defaults["aggressiveness"]) if isinstance(sa, str) else defaults["aggressiveness"],
                    "agent_mode": bool(am) if am is not None else defaults["agent_mode"],
                    "bug_bounty_mode": bool(bbm) if bbm is not None else defaults["bug_bounty_mode"],
                }
    except Exception:
        logger.warning("fetch_engagement_scan_options failed for %s", engagement_id, exc_info=True)
    return dict(defaults)
