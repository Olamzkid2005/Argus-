"""
Worker result cache for frequently accessed data

Uses Redis for distributed caching across workers.
Supports query result caching, TTL strategies, and cache invalidation.
"""

import hashlib
import json
import logging
import os
import re
import threading
from collections.abc import Callable
from enum import Enum
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)

# Redis configuration — use shared config for production, override allow cache isolation
import contextlib  # noqa: E402

from config.redis import REDIS_URL as _BASE_REDIS_URL  # noqa: E402

CACHE_DB = int(os.getenv("CACHE_REDIS_DB", "2"))
CACHE_REDIS_URL = os.getenv("CACHE_REDIS_URL", f"{_BASE_REDIS_URL}/{CACHE_DB}")

# Lazy Redis client with auto-reconnect on failure (not module-level)
_redis_client_instance = None
_redis_available = False
_redis_lock = threading.Lock()


def _get_redis():
    """Lazy-init Redis client with automatic reconnect on failure."""
    global _redis_client_instance, _redis_available
    with _redis_lock:
        if _redis_client_instance is not None:
            try:
                _redis_client_instance.ping()
                return _redis_client_instance
            except Exception:
                logger.warning("Redis connection lost — reconnecting")
                with contextlib.suppress(Exception):
                    _redis_client_instance.close()
                _redis_client_instance = None
                _redis_available = False
        try:
            import redis as redis_lib

            _redis_client_instance = redis_lib.from_url(
                CACHE_REDIS_URL, socket_connect_timeout=3, socket_timeout=3
            )
            _redis_client_instance.ping()
            _redis_available = True
            return _redis_client_instance
        except Exception as e:
            if not _redis_available:
                logger.debug("Redis still unavailable for caching: %s", e)
            else:
                logger.warning("Redis became unavailable for caching: %s", e)
            _redis_available = False
            return None


class CacheMode(Enum):
    """Cache execution modes for controlling read/write behavior.

    Enforced at the execution layer (tool_runner), not inside cache.py itself.
    cache.py remains a dumb storage layer.
    """

    NORMAL = "normal"  # Read cache, write cache (standard behavior)
    NO_CACHE = "no_cache"  # Skip reads AND writes (truly fresh scan)
    REFRESH = "refresh"  # Skip reads, still write (refresh stale data)


class CachePolicy:
    """Named TTL constants for per-data-type cache expiry.

    These are used as ttl values when calling WorkerCache.set(key, value, ttl=<policy>).
    The existing WorkerCache.set() API already supports per-call TTL overrides —
    this class just provides named constants for consistency.

    Sentinel values:
        -1 — No expiry (use Redis SET instead of SETEX).
             TTL values <= 0 are treated as sentinel and stored without expiry.
    """

    TOOL_QUERY = 300  # 5 min — tool results (quick-changing)
    TOOL_DETAIL = 86400 * 7  # 7 days — tool definitions/metadata (stable)
    ADVISORY_QUERY = 1800  # 30 min — advisory lookups (cve-lite-cli compat)
    ADVISORY_DETAIL = -1  # No expiry — advisory records are immutable
    ENGAGEMENT_STATE = 300  # 5 min — engagement state (existing default)


class WorkerCache:
    """Enhanced cache using Redis with query result caching and invalidation"""

    # TTL presets (seconds)
    TTL_SHORT = 60  # 1 minute
    TTL_MEDIUM = 300  # 5 minutes
    TTL_LONG = 3600  # 1 hour
    TTL_EXTENDED = 86400  # 24 hours
    # Namespace prefix to avoid key collisions with other Redis users on same DB
    KEY_PREFIX = "cache:"

    def __init__(self, ttl: int = 300):
        self.ttl = ttl
        # Cache observability counters (thread-safe)
        self._lock = threading.Lock()
        self._hit_count = 0
        self._miss_count = 0
        self._bypass_count = 0
        self._refresh_count = 0

    def _sanitize_key_component(self, component: str) -> str:
        """Sanitize a key component to prevent Redis key injection.

        Removes characters like newlines, colons at boundaries, and
        control characters that could be used for key injection.

        Args:
            component: Raw key component string

        Returns:
            Sanitized key component
        """
        safe = re.sub(r"[\x00-\x1f\x7f]", "", str(component))
        # Replace emtpy string after sanitization
        return safe or "_"

    def _key(self, k: str) -> str:
        return f"{self.KEY_PREFIX}{self._sanitize_key_component(k)}"

    def get(self, key: str) -> Any | None:
        """Get value from cache. Tracks hit/miss counters."""
        client = _get_redis()
        if not client:
            return None

        try:
            value = client.get(self._key(key))
            if value:
                with self._lock:
                    self._hit_count += 1
                return json.loads(value)
        except Exception as e:
            logger.error("Cache get error: %s", e)

        with self._lock:
            self._miss_count += 1
        return None

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Set value in cache.

        Supports TTL sentinel: ttl <= 0 means no expiry (uses Redis SET
        instead of SETEX). For ADVISORY_DETAIL and other immutable data
        that should never expire.

        Args:
            key: Cache key.
            value: Value to cache (serialized to JSON).
            ttl: TTL in seconds. If None, uses instance default.
                 If <= 0, stores without expiry (Redis SET, no TTL).

        Returns:
            True if cached successfully.
        """
        client = _get_redis()
        if not client:
            return False

        try:
            ttl = ttl if ttl is not None else self.ttl
            serialized = json.dumps(value)
            if ttl <= 0:
                # No-expiry sentinel — use SET instead of SETEX
                client.set(self._key(key), serialized)
            else:
                client.setex(self._key(key), ttl, serialized)
            return True
        except Exception as e:
            logger.error("Cache set error: %s", e)
            return False

    def delete(self, key: str) -> bool:
        """Delete value from cache"""
        client = _get_redis()
        if not client:
            return False

        try:
            client.delete(self._key(key))
            return True
        except Exception as e:
            logger.error("Cache delete error: %s", e)
            return False

    def clear_pattern(self, pattern: str) -> int:
        """Clear all keys matching pattern using SCAN to avoid blocking Redis"""
        client = _get_redis()
        if not client:
            return 0

        try:
            deleted = 0
            cursor = 0
            full_pattern = self._key(self._sanitize_key_component(pattern))
            while True:
                cursor, keys = client.scan(cursor, match=full_pattern, count=100)
                if keys:
                    deleted += client.delete(*keys)
                if cursor == 0:
                    break
            return deleted
        except Exception as e:
            logger.error("Cache clear error: %s", e)
            return 0

    def get_query_result(
        self, query: str, params: tuple | None = None, _ttl: int | None = None
    ) -> Any | None:
        """
        Get cached query result.

        Args:
            query: SQL query string
            params: Query parameters
            ttl: Cache TTL in seconds

        Returns:
            Cached result or None
        """
        key = self._query_key(query, params)
        return self.get(key)

    def set_query_result(
        self, query: str, params: tuple | None, result: Any, ttl: int | None = None
    ) -> bool:
        """
        Cache query result.

        Args:
            query: SQL query string
            params: Query parameters
            result: Query result to cache
            ttl: Cache TTL in seconds

        Returns:
            True if cached successfully
        """
        key = self._query_key(query, params)
        return self.set(key, result, ttl)

    def invalidate_query(self, query_pattern: str) -> int:
        """
        Invalidate cached queries matching pattern.

        Args:
            query_pattern: Pattern to match in query strings

        Returns:
            Number of keys removed
        """
        # TODO: Replace pattern-based clearing with tag-based invalidation
        # to avoid matching unintended keys. See Redis tags pattern.
        return self.clear_pattern(f"query:*{query_pattern}*")

    def invalidate_table(self, table_name: str) -> int:
        """
        Invalidate all cached queries for a table.

        Args:
            table_name: Table name to invalidate

        Returns:
            Number of keys removed
        """
        # Use a tag-based invalidation approach
        return self.clear_pattern(f"*table:{table_name}*")

    def _query_key(self, query: str, params: tuple | None = None) -> str:
        """Generate a cache key from the SQL query template and params.

        Uses the query template (with placeholders, not expanded values)
        to prevent cache key collisions from user-controlled data.
        Includes params in the key so different parameter sets produce
        different cache entries.
        """
        # Normalize the query template by stripping whitespace
        normalized_query = ' '.join(query.split())
        # Include params in the key data so different params = different cache entries
        key_parts = [normalized_query]
        if params:
            key_parts.append(json.dumps(params, sort_keys=True))
        key_data = ":".join(key_parts)
        hash_value = hashlib.sha256(key_data.encode()).hexdigest()[:16]
        return f"query:{hash_value}"

    def record_bypass(self) -> None:
        """Increment NO_CACHE mode bypass counter."""
        with self._lock:
            self._bypass_count += 1

    def record_refresh(self) -> None:
        """Increment REFRESH mode refresh counter."""
        with self._lock:
            self._refresh_count += 1

    def get_metrics(self) -> dict:
        """Get cache access metrics (hit/miss/bypass/refresh).

        Returns in-memory counters, not cluster-level Redis stats.
        """
        with self._lock:
            total = self._hit_count + self._miss_count
            return {
                "hit_count": self._hit_count,
                "miss_count": self._miss_count,
                "bypass_count": self._bypass_count,
                "refresh_count": self._refresh_count,
                "hit_rate": round(self._hit_count / total, 4) if total > 0 else 0.0,
            }

    def get_stats(self) -> dict:
        """Get cache statistics (Redis keyspace + local metrics)."""
        metrics = self.get_metrics()
        client = _get_redis()
        if not client:
            return {"status": "unavailable", **metrics}

        try:
            info = client.info("keyspace")
            db_info = info.get(f"db{CACHE_DB}", {})
            return {
                "status": "available",
                "keys": db_info.get("keys", 0),
                "expires": db_info.get("expires", 0),
                **metrics,
            }
        except Exception as e:
            logger.error("Cache stats error: %s", e)
            return {"status": "error", "error": str(e), **metrics}


# Global cache instance
cache = WorkerCache(ttl=300)  # 5 minute default TTL


class _CachedFunc:
    """Wrapper type that carries a cache_invalidate method."""

    def __init__(self, func: Callable, invalidate: Callable[[], int]):
        from functools import update_wrapper

        self.__wrapped__ = func
        self._func = func
        self._invalidate = invalidate
        update_wrapper(self, func)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._func(*args, **kwargs)

    def cache_invalidate(self) -> int:
        return self._invalidate()


def cached(
    key_prefix: str, ttl: int | None = None, invalidate_on: list[str] | None = None
):
    """
    Decorator for caching function results.

    Args:
        key_prefix: Prefix for cache key
        ttl: Cache TTL in seconds
        invalidate_on: List of table names that should invalidate this cache
    """
    _MISS = object()

    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = f"{key_prefix}:{':'.join(map(str, args))}"

            cached_value = cache.get(key)
            if cached_value is not None:
                return cached_value

            result = func(*args, **kwargs)

            if result is not None:
                cache.set(key, result, ttl)

            return result

        # Return a _CachedFunc instead of attaching attribute to wrapper
        return _CachedFunc(
            wrapper,
            invalidate=lambda: cache.clear_pattern(f"{key_prefix}:*"),
        )

    return decorator


def cached_query(ttl: int = 300):
    """
    Decorator for caching database query results.

    Args:
        ttl: Cache TTL in seconds
    """

    def decorator(func: Callable):
        # Derive a prefix from the function name for scoped invalidation
        func_prefix = f"cached_query:{func.__name__}"

        @wraps(func)
        def wrapper(*args, **kwargs):
            # Generate cache key from function name and args
            key_data = f"{func.__name__}:{json.dumps(args)}:{json.dumps(kwargs, sort_keys=True)}"
            key = f"query:{hashlib.sha256(key_data.encode()).hexdigest()[:16]}"

            # Try cache first
            cached_value = cache.get(key)
            if cached_value is not None:
                return cached_value

            # Execute function
            result = func(*args, **kwargs)

            # Store in cache
            cache.set(key, result, ttl)

            return result

        return _CachedFunc(
            wrapper,
            # Scope invalidation to this function's keys using the hash prefix
            invalidate=lambda: cache.clear_pattern(f"*cached_query:{func.__name__}*"),
        )

    return decorator
