"""
Worker result cache for frequently accessed data

Uses Redis for distributed caching across workers
"""

import json
import logging
import os
from typing import Any, Optional
from functools import wraps

logger = logging.getLogger(__name__)

# Redis configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# Try to import redis, but make it optional
try:
    import redis as redis_lib

    _redis_client = redis_lib.from_url(f"{REDIS_URL}/1")  # Use DB 1 for cache
    _redis_available = True
except Exception as e:
    logger.warning(f"Redis not available for caching: {e}")
    _redis_client = None
    _redis_available = False


class WorkerCache:
    """Simple cache using Redis"""
    
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


# Global cache instance
cache = WorkerCache(ttl=300)  # 5 minute default TTL


def cached(key_prefix: str, ttl: Optional[int] = None):
    """Decorator for caching function results"""
    def decorator(func):
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
        
        return wrapper
    return decorator