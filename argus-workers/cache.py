"""
Worker result cache for frequently accessed data

Uses Redis for distributed caching across workers.
Supports query result caching, TTL strategies, and cache invalidation.
"""

import hashlib
import json
import logging
import os
from collections.abc import Callable
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)

# Redis configuration — use shared config for production, override allow cache isolation
import contextlib  # noqa: E402

from config.redis import REDIS_URL as _BASE_REDIS_URL  # noqa: E402

CACHE_DB = int(os.getenv("CACHE_REDIS_DB", "1"))
CACHE_REDIS_URL = os.getenv("CACHE_REDIS_URL", f"{_BASE_REDIS_URL}/{CACHE_DB}")

# Lazy Redis client with auto-reconnect on failure (not module-level)
_redis_client_instance = None
_redis_available = False


def _get_redis():
    """Lazy-init Redis client with automatic reconnect on failure."""
    global _redis_client_instance, _redis_available
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
        _redis_client_instance = redis_lib.from_url(CACHE_REDIS_URL, socket_connect_timeout=3, socket_timeout=3)
        _redis_client_instance.ping()
        _redis_available = True
        return _redis_client_instance
    except Exception as e:
        if not _redis_available:
            logger.debug("Redis still unavailable for caching: %s", e)
        else:
            logger.warning(f"Redis became unavailable for caching: {e}")
        _redis_available = False
        return None


class WorkerCache:
    """Enhanced cache using Redis with query result caching and invalidation"""

    # TTL presets (seconds)
    TTL_SHORT = 60       # 1 minute
    TTL_MEDIUM = 300     # 5 minutes
    TTL_LONG = 3600      # 1 hour
    TTL_EXTENDED = 86400 # 24 hours
    # Namespace prefix to avoid key collisions with other Redis users on same DB
    KEY_PREFIX = "cache:"

    def __init__(self, ttl: int = 300):
        self.ttl = ttl

    def _key(self, k: str) -> str:
        return f"{self.KEY_PREFIX}{k}"

    def get(self, key: str) -> Any | None:
        """Get value from cache"""
        client = _get_redis()
        if not client:
            return None

        try:
            value = client.get(self._key(key))
            if value:
                return json.loads(value)
        except Exception as e:
            logger.error(f"Cache get error: {e}")

        return None

    def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Set value in cache"""
        client = _get_redis()
        if not client:
            return False

        try:
            ttl = ttl or self.ttl
            client.setex(self._key(key), ttl, json.dumps(value))
            return True
        except Exception as e:
            logger.error(f"Cache set error: {e}")
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
            logger.error(f"Cache delete error: {e}")
            return False

    def clear_pattern(self, pattern: str) -> int:
        """Clear all keys matching pattern using SCAN to avoid blocking Redis"""
        client = _get_redis()
        if not client:
            return 0

        try:
            deleted = 0
            cursor = 0
            full_pattern = self._key(pattern)
            while True:
                cursor, keys = client.scan(cursor, match=full_pattern, count=100)
                if keys:
                    deleted += client.delete(*keys)
                if cursor == 0:
                    break
            return deleted
        except Exception as e:
            logger.error(f"Cache clear error: {e}")
            return 0

    def get_query_result(
        self,
        query: str,
        params: tuple | None = None,
        _ttl: int | None = None
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
        self,
        query: str,
        params: tuple | None,
        result: Any,
        ttl: int | None = None
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

    def _query_key(self, query: str, params: tuple | None) -> str:
        """Generate cache key for a query"""
        key_data = f"{query}:{json.dumps(params) if params else ''}"
        hash_value = hashlib.sha256(key_data.encode()).hexdigest()[:16]
        return f"query:{hash_value}"

    def get_stats(self) -> dict:
        """Get cache statistics"""
        client = _get_redis()
        if not client:
            return {"status": "unavailable"}

        try:
            info = client.info("keyspace")
            db_info = info.get(f"db{CACHE_DB}", {})
            return {
                "status": "available",
                "keys": db_info.get("keys", 0),
                "expires": db_info.get("expires", 0),
            }
        except Exception as e:
            logger.error(f"Cache stats error: {e}")
            return {"status": "error", "error": str(e)}


# Global cache instance
cache = WorkerCache(ttl=300)  # 5 minute default TTL


def cached(key_prefix: str, ttl: int | None = None, invalidate_on: list[str] | None = None):
    """
    Decorator for caching function results.

    Args:
        key_prefix: Prefix for cache key
        ttl: Cache TTL in seconds
        invalidate_on: List of table names that should invalidate this cache
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Generate cache key
            key = f"{key_prefix}:{':'.join(map(str, args))}"

            # Try cache first
            cached_value = cache.get(key)
            if cached_value is not None:
                return cached_value

            # Execute function
            result = func(*args, **kwargs)

            # Store in cache
            cache.set(key, result, ttl)

            return result

        # Attach invalidation helper
        wrapper.cache_invalidate = lambda: cache.clear_pattern(f"{key_prefix}:*")

        return wrapper
    return decorator


def cached_query(ttl: int = 300):
    """
    Decorator for caching database query results.

    Args:
        ttl: Cache TTL in seconds
    """
    def decorator(func: Callable):
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

        wrapper.cache_invalidate = lambda: cache.clear_pattern("query:*")
        return wrapper
    return decorator
