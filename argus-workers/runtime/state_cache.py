"""
RedisStateCache — Redis fast-access cache for EngagementState snapshots.

Implements the Redis persistence requirement from the Agent Runtime Refactor
spec (Rule 2: "EngagementState MUST persist to Redis + Postgres"). The Redis
cache provides sub-millisecond reads for the hot path (agent loop iterations)
while Postgres provides durable snapshot storage for recovery.

Cache Strategy:
  - Write-through on state mutation (save to both Redis + Postgres)
  - TTL-based expiry for stale data (default 5 min, extended on each save)
  - Graceful degradation — Redis failures are logged, not raised
  - Cross-worker consistency via Redis key TTL + version checks

Usage:
    cache = RedisStateCache()
    cache.save(engagement_id, state_dict)
    cached = cache.load(engagement_id)
    cache.delete(engagement_id)
    cache.touch(engagement_id)  # extend TTL
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

# ── Key namespace ──

STATE_CACHE_KEY = "engagement_state:{engagement_id}"
STATE_CACHE_TTL = 300  # 5 minutes default


class RedisStateCache:
    """Redis-backed fast-access cache for EngagementState snapshots.

    Designed for sub-millisecond reads during the agent loop hot path.
    Falls back gracefully to None if Redis is unavailable — never raises.
    """

    def __init__(self, redis_url: str | None = None, ttl: int = STATE_CACHE_TTL):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        self.ttl = ttl
        self._client = None

    # ── Connection management ──

    def _get_client(self):
        """Lazy-init Redis client with graceful degradation."""
        if self._client is not None:
            try:
                self._client.ping()
                return self._client
            except Exception:
                logger.warning("Redis connection lost — reconnecting")
                self._client = None

        try:
            import redis as redis_module

            self._client = redis_module.from_url(
                self.redis_url,
                socket_connect_timeout=2,
                socket_timeout=2,
                decode_responses=True,
            )
            self._client.ping()
            return self._client
        except Exception as e:
            logger.debug("Redis unavailable for state cache: %s", e)
            return None

    # ── Key helpers ──

    @staticmethod
    def _key(engagement_id: str) -> str:
        return STATE_CACHE_KEY.format(engagement_id=engagement_id)

    # ── Public API ──

    def save(self, engagement_id: str, state_data: dict) -> bool:
        """Save an EngagementState snapshot to Redis.

        Args:
            engagement_id: Engagement UUID.
            state_data: Dict from EngagementState.to_dict() or to_snapshot_dict().

        Returns:
            True if saved successfully, False if Redis is unavailable.
        """
        client = self._get_client()
        if not client:
            return False
        try:
            key = self._key(engagement_id)
            client.setex(key, self.ttl, json.dumps(state_data, default=str))
            return True
        except Exception as e:
            logger.warning("Failed to save state cache for %s: %s", engagement_id, e)
            return False

    def load(self, engagement_id: str) -> dict | None:
        """Load an EngagementState snapshot from Redis.

        Args:
            engagement_id: Engagement UUID.

        Returns:
            Dict with state data, or None if not cached / Redis unavailable.
        """
        client = self._get_client()
        if not client:
            return None
        try:
            key = self._key(engagement_id)
            raw = client.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as e:
            logger.warning("Failed to load state cache for %s: %s", engagement_id, e)
            return None

    def delete(self, engagement_id: str) -> bool:
        """Remove an EngagementState from Redis cache.

        Called when an engagement completes or fails, or when the state is
        explicitly invalidated.

        Returns:
            True if deleted or key didn't exist, False on error.
        """
        client = self._get_client()
        if not client:
            return False
        try:
            key = self._key(engagement_id)
            client.delete(key)
            return True
        except Exception as e:
            logger.warning("Failed to delete state cache for %s: %s", engagement_id, e)
            return False

    def touch(self, engagement_id: str) -> bool:
        """Extend the TTL for a cached EngagementState.

        Useful in long-running agent loops to prevent the state from expiring
        mid-engagement. Called after each successful state mutation.

        Returns:
            True if TTL extended, False if key doesn't exist or Redis unavailable.
        """
        client = self._get_client()
        if not client:
            return False
        try:
            key = self._key(engagement_id)
            return bool(client.expire(key, self.ttl))
        except Exception as e:
            logger.warning("Failed to touch state cache for %s: %s", engagement_id, e)
            return False

    @property
    def is_available(self) -> bool:
        """Check if Redis is available for caching (lazy-init check)."""
        return self._get_client() is not None


# ── Module-level convenience instance ──

_state_cache: RedisStateCache | None = None


def get_state_cache(redis_url: str | None = None) -> RedisStateCache:
    """Get or create the global RedisStateCache instance.

    Args:
        redis_url: Optional Redis URL override.

    Returns:
        RedisStateCache singleton.
    """
    global _state_cache
    if _state_cache is None:
        _state_cache = RedisStateCache(redis_url=redis_url)
    return _state_cache


def save_state(engagement_id: str, state_data: dict) -> bool:
    """Convenience: save engagement state to Redis cache."""
    return get_state_cache().save(engagement_id, state_data)


def load_state(engagement_id: str) -> dict | None:
    """Convenience: load engagement state from Redis cache."""
    return get_state_cache().load(engagement_id)


def delete_state(engagement_id: str) -> bool:
    """Convenience: delete engagement state from Redis cache."""
    return get_state_cache().delete(engagement_id)


def touch_state(engagement_id: str) -> bool:
    """Convenience: extend TTL for cached engagement state."""
    return get_state_cache().touch(engagement_id)
