"""
Distributed Lock - Prevents multiple workers from processing same engagement
"""

import logging
import time
import uuid

import redis
from exceptions import LockAcquisitionError

logger = logging.getLogger(__name__)


class DistributedLock:
    """
    Redis-based distributed lock with heartbeat mechanism
    """

    # Lock TTL: 3600 seconds (1 hour) to match maximum task timeout
    LOCK_TTL_SECONDS = 3600

    # Heartbeat interval: 60 seconds
    HEARTBEAT_INTERVAL_SECONDS = 60

    def __init__(self, redis_url: str, worker_id: str | None = None):
        """
        Initialize Distributed Lock

        Args:
            redis_url: Redis connection URL
            worker_id: Unique worker identifier (generated if not provided)
        """
        self.redis_url = redis_url
        self._redis_client = None
        self.worker_id = worker_id or str(uuid.uuid4())
        self.held_locks = {}  # engagement_id -> lock_key mapping

    @property
    def redis_client(self) -> redis.Redis:
        """Lazy Redis client with auto-reconnect (M6 fix).

        On ConnectionError, recreates the client to recover from
        transient Redis outages. The old client is discarded so the
        next call establishes a fresh connection.
        """
        if self._redis_client is None:
            self._redis_client = redis.Redis.from_url(
                self.redis_url,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
            )
        return self._redis_client

    @redis_client.setter
    def redis_client(self, client: redis.Redis) -> None:
        self._redis_client = client

    def _with_reconnect(self, method_name: str, *args, **kwargs):
        """Execute a Redis operation with auto-reconnect on failure (M6).

        Accepts a method name string rather than a bound method so the
        retry uses a fresh client instance after reconnect.

        Attempts the operation once. If it fails with a connection error,
        discards the stale client and retries once. If both attempts fail,
        propagates the exception.
        """
        try:
            operation = getattr(self.redis_client, method_name)
            return operation(*args, **kwargs)
        except (redis.ConnectionError, redis.TimeoutError, OSError) as e:
            logger.warning("Redis connection lost, attempting reconnect: %s", e)
            self._redis_client = None  # Discard stale client
            try:
                operation = getattr(self.redis_client, method_name)
                return operation(*args, **kwargs)
            except (redis.ConnectionError, redis.TimeoutError, OSError) as e2:
                logger.error("Redis reconnect failed: %s", e2)
                raise

    def acquire(self, engagement_id: str, ttl_override: int | None = None) -> bool:
        """
        Attempt to acquire lock on engagement

        Uses Redis SET with NX flag (only if not exists) and expiration.

        Args:
            engagement_id: Engagement ID to lock
            ttl_override: Optional custom TTL for this lock (defaults to LOCK_TTL_SECONDS)

        Returns:
            True if lock acquired, False if already held by another worker
        """
        lock_key = f"engagement_lock:{engagement_id}"
        ttl = ttl_override or self.LOCK_TTL_SECONDS

        # Try to acquire lock with NX flag and expiration
        acquired = self._with_reconnect(
            "set",
            lock_key,
            self.worker_id,
            nx=True,  # Only set if not exists
            ex=ttl,  # Expiration in seconds
        )

        if acquired:
            # Store lock key for heartbeat
            self.held_locks[engagement_id] = {
                "key": lock_key,
                "expires_at": time.time() + ttl,
            }
            return True

        # Check if we already hold this lock
        current_holder = self._with_reconnect("get", lock_key)
        if current_holder and current_holder.decode("utf-8") == self.worker_id:
            # We already hold this lock — extend it to prevent expiry during long operations
            self.extend(engagement_id)
            self.held_locks[engagement_id] = {
                "key": lock_key,
                "expires_at": time.time() + ttl,
            }
            return True

        # Check if lock is stale (expired key but not cleaned up)
        if not current_holder:
            # Key expired between check and get — retry acquire
            return self.acquire(engagement_id, ttl)

        # Lock held by another worker
        return False

    def release(self, engagement_id: str) -> bool:
        """
        Release lock on engagement

        Uses Lua script to verify ownership before deletion.
        Ensures locks are released even on cancellation.

        Only removes from held_locks when Redis confirms ownership (H4).
        If the lock expired or another worker owns it, we keep it in
        held_locks so release_all() can attempt cleanup later.

        Args:
            engagement_id: Engagement ID to unlock

        Returns:
            True if lock released, False if not held by this worker
        """
        lock_key = f"engagement_lock:{engagement_id}"

        # Lua script to verify ownership before deletion
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """

        # Execute Lua script with auto-reconnect (M6)
        try:
            result = self._with_reconnect(
                "eval", lua_script, 1, lock_key, self.worker_id
            )
        except Exception:
            # Redis unavailable — don't touch held_locks, attempt to close cleanly
            logger.warning(
                "Redis unavailable during release of engagement %s", engagement_id
            )
            return False

        if result == 1:
            # Lock successfully released — remove from held_locks
            if engagement_id in self.held_locks:
                del self.held_locks[engagement_id]
            return True

        # Lock not owned by us (expired or another worker holds it)
        # Keep it in held_locks for diagnostic purposes (H4) — release_all()
        # will still try to clean up, and the stale entry will be overwritten
        # on next acquire() for this engagement.
        logger.warning(
            "Failed to release lock for engagement %s — lock may have expired or is held by another worker. "
            "Keeping held_locks entry for diagnostics.",
            engagement_id,
        )
        return False

    def extend(self, engagement_id: str) -> bool:
        """
        Extend lock TTL (heartbeat mechanism)

        Should be called regularly while processing continues.
        Re-acquires the lock with a fresh TTL to handle long-running scans.

        Args:
            engagement_id: Engagement ID

        Returns:
            True if lock extended, False if not held by this worker
        """
        lock_key = f"engagement_lock:{engagement_id}"

        # Use SET with XX (update only if exists) to refresh TTL atomically
        # This is simpler and safer than the Lua script approach
        result = self._with_reconnect(
            "set",
            lock_key,
            self.worker_id,
            xx=True,  # Only update if key exists
            ex=self.LOCK_TTL_SECONDS,
        )

        if result:
            # Update held_locks tracking
            if engagement_id in self.held_locks:
                self.held_locks[engagement_id] = {
                    "key": lock_key,
                    "expires_at": time.time() + self.LOCK_TTL_SECONDS,
                }
            return True

        return False

    def is_locked(self, engagement_id: str) -> bool:
        """
        Check if engagement is locked

        Args:
            engagement_id: Engagement ID

        Returns:
            True if locked (by any worker)
        """
        lock_key = f"engagement_lock:{engagement_id}"
        try:
            return self._with_reconnect("exists", lock_key) > 0
        except Exception:
            logger.debug("Failed to check lock for %s", engagement_id)
            return False

    def get_lock_holder(self, engagement_id: str) -> str | None:
        """
        Get worker ID that holds the lock

        Args:
            engagement_id: Engagement ID

        Returns:
            Worker ID or None if not locked
        """
        lock_key = f"engagement_lock:{engagement_id}"
        try:
            holder = self._with_reconnect("get", lock_key)
        except Exception:
            logger.debug("Failed to get lock holder for %s", engagement_id)
            return None

        if holder:
            return holder.decode("utf-8")

        return None

    def release_all(self):
        """Release all locks held by this worker"""
        for engagement_id in list(self.held_locks.keys()):
            self.release(engagement_id)

    def heartbeat_loop(
        self, engagement_id: str, is_done_callback, interval_seconds: int | None = None
    ):
        """
        Run heartbeat loop to extend lock while processing

        Uses exponential backoff on extend failures — if extending fails,
        retries more frequently to regain the lock before TTL expires.

        Args:
            engagement_id: Engagement ID
            is_done_callback: Function that returns True when processing is done
            interval_seconds: Heartbeat interval (defaults to HEARTBEAT_INTERVAL_SECONDS)
        """
        interval = interval_seconds or self.HEARTBEAT_INTERVAL_SECONDS
        consecutive_failures = 0

        while not is_done_callback():
            time.sleep(interval)

            if not self.extend(engagement_id):
                consecutive_failures += 1
                logger.warning(
                    "Failed to extend lock for engagement %s (attempt %d)",
                    engagement_id,
                    consecutive_failures,
                )
                if consecutive_failures >= 3:
                    logger.error(
                        "Lost lock for engagement %s after %d failed extend attempts — "
                        "re-acquiring with ownership check",
                        engagement_id,
                        consecutive_failures,
                    )
                    # Re-acquire with NX flag and ownership verification to avoid
                    # force-deleting another worker's lock. If the original TTL is
                    # still valid, the lock belongs to us and we can extend it via
                    # SET XX. If it expired and another worker took it, acquire()
                    # will fail cleanly.
                    if not self.acquire(engagement_id):
                        logger.error(
                            "Lost lock for engagement %s — another worker has acquired it",
                            engagement_id,
                        )
                    else:
                        logger.info("Re-acquired lock for engagement %s", engagement_id)
                    break
                # Retry more frequently after failure
                interval = max(5, interval // 2)
            else:
                consecutive_failures = 0
                interval = interval_seconds or self.HEARTBEAT_INTERVAL_SECONDS


class LockContext:
    """
    Context manager for distributed locks
    """

    def __init__(self, lock: DistributedLock, engagement_id: str):
        """
        Initialize lock context

        Args:
            lock: DistributedLock instance
            engagement_id: Engagement ID to lock
        """
        self.lock = lock
        self.engagement_id = engagement_id
        self.acquired = False

    def __enter__(self):
        """Acquire lock on enter"""
        self.acquired = self.lock.acquire(self.engagement_id)

        if not self.acquired:
            holder = self.lock.get_lock_holder(self.engagement_id)
            raise LockAcquisitionError(
                f"Failed to acquire lock for engagement {self.engagement_id}. "
                f"Held by worker: {holder}"
            )

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Release lock on exit"""
        if self.acquired:
            self.lock.release(self.engagement_id)
