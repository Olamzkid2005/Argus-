"""
Global concurrency management for tool execution.

Provides a combined distributed + local semaphore system:
1. Redis-based distributed semaphore (cross-worker coordination) when Redis is available
2. Threading-based local semaphore as fallback when Redis is unavailable

The distributed Redis semaphore uses SETNX with TTL for atomic acquire/release.
"""

import os
import threading
import time

from config.constants import MAX_CONCURRENT_REQUESTS

# Local fallback semaphore (per-process, used when Redis is unavailable)
_LOCAL_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT_REQUESTS)

# Stricter local semaphore for high-cost / destructive tools
HIGH_COST_TOOLS = {"sqlmap", "dalfox", "commix", "nuclei", "masscan", "sn1per"}
_HIGH_COST_LOCAL = threading.BoundedSemaphore(max(1, MAX_CONCURRENT_REQUESTS // 3))

# Redis-based distributed semaphore
_REDIS_SEM_KEY = "argus:concurrency:semaphore"
_REDIS_HIGH_COST_KEY = "argus:concurrency:high_cost"
_SEM_TTL = 300  # 5 minutes max lease


def _get_redis():
    """Lazy-init Redis client for distributed coordination."""
    try:
        import redis as redis_module
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        return redis_module.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
    except Exception:
        return None


class DistributedSemaphore:
    """Distributed semaphore backed by Redis SETNX with local fallback."""

    def __init__(self, redis_key: str, max_count: int, local_semaphore: threading.BoundedSemaphore):
        self._redis_key = redis_key
        self._max_count = max_count
        self._local = local_semaphore
        self._r: object | None = None

    def _ensure_redis(self):
        if self._r is None:
            self._r = _get_redis()

    def acquire(self, timeout: float = 30.0) -> bool:
        """Acquire the semaphore, trying Redis first, falling back to local."""
        self._ensure_redis()
        if self._r is not None:
            try:
                return self._acquire_redis(timeout)
            except Exception:
                pass  # Fall through to local
        self._local.acquire()
        return True

    def _acquire_redis(self, timeout: float) -> bool:
        """Redis-based distributed acquire with Lua scripting (blocker 54).

        Uses a Lua script to atomically check-and-increment, eliminating the
        TOCTOU window between GET and INCR that existed in the original
        non-atomic implementation. The script returns 1 on success (slot
        acquired) or 0 on failure (all slots busy).
        """
        r = self._r
        _lua_acquire = """
            local current = redis.call('GET', KEYS[1])
            local count = tonumber(current or 0)
            if count < tonumber(ARGV[1]) then
                redis.call('INCR', KEYS[1])
                redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
                return 1
            end
            return 0
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                acquired = r.eval(_lua_acquire, 1, self._redis_key, self._max_count, _SEM_TTL)
                if acquired == 1:
                    return True
            except Exception:
                pass  # Redis down — fall through to local fallback
            time.sleep(0.1)
        return False

    def release(self):
        """Release the semaphore."""
        self._ensure_redis()
        if self._r is not None:
            try:
                current = self._r.get(self._redis_key)
                if current and int(current) > 0:
                    self._r.decr(self._redis_key)
                return
            except Exception:
                pass
        self._local.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()


# Global semaphore instances
SUBPROCESS_SEMAPHORE = DistributedSemaphore(
    _REDIS_SEM_KEY, MAX_CONCURRENT_REQUESTS, _LOCAL_SEMAPHORE
)

HIGH_COST_SEMAPHORE = DistributedSemaphore(
    _REDIS_HIGH_COST_KEY, max(1, MAX_CONCURRENT_REQUESTS // 3), _HIGH_COST_LOCAL
)
