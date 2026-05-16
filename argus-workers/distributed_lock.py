"""
Distributed Lock - Prevents multiple workers from processing same engagement
"""
import logging
import time
import uuid

import redis

logger = logging.getLogger(__name__)


class LockAcquisitionError(Exception):
    """Raised when a distributed lock cannot be acquired (transient, retryable)."""
    pass


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
        self.redis_client = redis.Redis.from_url(
            redis_url,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        self.worker_id = worker_id or str(uuid.uuid4())
        self.held_locks = {}  # engagement_id -> lock_key mapping

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
        acquired = self.redis_client.set(
            lock_key,
            self.worker_id,
            nx=True,  # Only set if not exists
            ex=ttl  # Expiration in seconds
        )

        if acquired:
            # Store lock key for heartbeat
            self.held_locks[engagement_id] = {
                "key": lock_key,
                "expires_at": time.time() + ttl,
            }
            return True

        # Check if we already hold this lock
        current_holder = self.redis_client.get(lock_key)
        if current_holder and current_holder.decode('utf-8') == self.worker_id:
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

        # Execute Lua script
        result = self.redis_client.eval(lua_script, 1, lock_key, self.worker_id)

        # Remove from held locks
        if engagement_id in self.held_locks:
            del self.held_locks[engagement_id]

        if result != 1:
            logger.warning(
                "Failed to release lock for engagement %s — lock may have expired or is held by another worker",
                engagement_id,
            )

        return result == 1

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
        from redis.client import NEVER_DECODE
        result = self.redis_client.set(
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
        return self.redis_client.exists(lock_key) > 0

    def get_lock_holder(self, engagement_id: str) -> str | None:
        """
        Get worker ID that holds the lock

        Args:
            engagement_id: Engagement ID

        Returns:
            Worker ID or None if not locked
        """
        lock_key = f"engagement_lock:{engagement_id}"
        holder = self.redis_client.get(lock_key)

        if holder:
            return holder.decode('utf-8')

        return None

    def release_all(self):
        """Release all locks held by this worker"""
        for engagement_id in list(self.held_locks.keys()):
            self.release(engagement_id)

    def heartbeat_loop(self, engagement_id: str, stop_callback, interval_seconds: int | None = None):
        """
        Run heartbeat loop to extend lock while processing

        Uses exponential backoff on extend failures — if extending fails,
        retries more frequently to regain the lock before TTL expires.

        Args:
            engagement_id: Engagement ID
            stop_callback: Function that returns True when processing is done
            interval_seconds: Heartbeat interval (defaults to HEARTBEAT_INTERVAL_SECONDS)
        """
        interval = interval_seconds or self.HEARTBEAT_INTERVAL_SECONDS
        consecutive_failures = 0

        while not stop_callback():
            time.sleep(interval)

            if not self.extend(engagement_id):
                consecutive_failures += 1
                logger.warning(
                    "Failed to extend lock for engagement %s (attempt %d)",
                    engagement_id, consecutive_failures,
                )
                if consecutive_failures >= 3:
                    logger.error(
                        "Lost lock for engagement %s after %d failed extend attempts — force-deleting stale key",
                        engagement_id, consecutive_failures,
                    )
                    force_key = f"engagement_lock:{engagement_id}"
                    try:
                        self.redis_client.delete(force_key)
                        logger.info("Force-deleted stale lock key for engagement %s", engagement_id)
                    except Exception as del_err:
                        logger.error("Failed to force-delete stale lock key for %s: %s", engagement_id, del_err)
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
