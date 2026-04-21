"""
Worker result cache for frequently accessed data

Uses Redis for distributed caching across workers.
Supports query result caching, TTL strategies, and cache invalidation.
"""

import json
import logging
import os
import hashlib
import time
from typing import Any, Optional, List, Callable
from functools import wraps

logger = logging.getLogger(__name__)

# Redis configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
CACHE_DB = int(os.getenv("CACHE_REDIS_DB", "1"))

# Try to import redis, but make it optional
try:
    import redis as redis_lib

    _redis_client = redis_lib.from_url(f"{REDIS_URL}/{CACHE_DB}")
    _redis_available = True
except Exception as e:
    logger.warning(f"Redis not available for caching: {e}")
    _redis_client = None
    _redis_available = False


class WorkerCache:
    """Enhanced cache using Redis with query result caching and invalidation"""
    
    # TTL presets (seconds)
    TTL_SHORT = 60       # 1 minute
    TTL_MEDIUM = 300     # 5 minutes
    TTL_LONG = 3600      # 1 hour
    TTL_EXTENDED = 86400 # 24 hours
    
    def __init__(self, ttl: int = 300):
        self.ttl = ttl
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        if not _redis_available:
            return None
        
        try:
            value = _redis_client.get(key)
            if value:
                return json.loads(value)
        except Exception as e:
            logger.error(f"Cache get error: {e}")
        
        return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set value in cache"""
        if not _redis_available:
            return False
        
        try:
            ttl = ttl or self.ttl
            _redis_client.setex(key, ttl, json.dumps(value))
            return True
        except Exception as e:
            logger.error(f"Cache set error: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """Delete value from cache"""
        if not _redis_available:
            return False
        
        try:
            _redis_client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Cache delete error: {e}")
            return False
    
    def clear_pattern(self, pattern: str) -> int:
        """Clear all keys matching pattern"""
        if not _redis_available:
            return 0
        
        try:
            keys = _redis_client.keys(pattern)
            if keys:
                return _redis_client.delete(*keys)
        except Exception as e:
            logger.error(f"Cache clear error: {e}")
        
        return 0
    
    def get_query_result(
        self,
        query: str,
        params: Optional[tuple] = None,
        ttl: Optional[int] = None
    ) -> Optional[Any]:
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
        params: Optional[tuple],
        result: Any,
        ttl: Optional[int] = None
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
    
    def _query_key(self, query: str, params: Optional[tuple]) -> str:
        """Generate cache key for a query"""
        key_data = f"{query}:{json.dumps(params) if params else ''}"
        hash_value = hashlib.sha256(key_data.encode()).hexdigest()[:16]
        return f"query:{hash_value}"
    
    def get_stats(self) -> dict:
        """Get cache statistics"""
        if not _redis_available:
            return {"status": "unavailable"}
        
        try:
            info = _redis_client.info("keyspace")
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


def cached(key_prefix: str, ttl: Optional[int] = None, invalidate_on: Optional[List[str]] = None):
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
            key = f"cache:{key_prefix}:{':'.join(map(str, args))}"
            
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
        wrapper.cache_invalidate = lambda: cache.clear_pattern(f"cache:{key_prefix}:*")
        
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
        
        wrapper.cache_invalidate = lambda: cache.clear_pattern(f"query:*")
        return wrapper
    return decorator