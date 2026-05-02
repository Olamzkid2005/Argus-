"""
Distributed Lock - Prevents multiple workers from processing same engagement
"""
import time
import uuid

import redis


class DistributedLock:
    """
    Redis-based distributed lock with heartbeat mechanism
    """

    # Lock TTL: 300 seconds (5 minutes)
    LOCK_TTL_SECONDS = 300

    # Heartbeat interval: 60 seconds
    HEARTBEAT_INTERVAL_SECONDS = 60

    def __init__(self, redis_url: str, worker_id: str | None = None):
        """
        Initialize Distributed Lock

        Args:
            redis_url: Redis connection URL
            worker_id: Unique worker identifier (generated if not provided)
        """
        self.redis_client = redis.Redis.from_url(redis_url)
        self.worker_id = worker_id or str(uuid.uuid4())
        self.held_locks = {}  # engagement_id -> lock_key mapping

    def acquire(self, engagement_id: str) -> bool:
        """
        Attempt to acquire lock on engagement

        Uses Redis SET with NX flag (only if not exists) and expiration.

        Args:
            engagement_id: Engagement ID to lock

        Returns:
            True if lock acquired, False if already held by another worker
        """
        lock_key = f"engagement_lock:{engagement_id}"

        # Try to acquire lock with NX flag and expiration
        acquired = self.redis_client.set(
            lock_key,
            self.worker_id,
            nx=True,  # Only set if not exists
            ex=self.LOCK_TTL_SECONDS  # Expiration in seconds
        )

        if acquired:
            # Store lock key for heartbeat
            self.held_locks[engagement_id] = lock_key
            return True

        # Check if we already hold this lock
        current_holder = self.redis_client.get(lock_key)
        if current_holder and current_holder.decode('utf-8') == self.worker_id:
            # We already hold this lock
            self.held_locks[engagement_id] = lock_key
            return True

        # Lock held by another worker
        return False

    def release(self, engagement_id: str) -> bool:
        """
        Release lock on engagement

        Uses Lua script to verify ownership before deletion.

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

        return result == 1

    def extend(self, engagement_id: str) -> bool:
        """
        Extend lock TTL (heartbeat mechanism)

        Should be called every 60 seconds while processing continues.

        Args:
            engagement_id: Engagement ID

        Returns:
            True if lock extended, False if not held by this worker
        """
        lock_key = f"engagement_lock:{engagement_id}"

        # Lua script to verify ownership before extending
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("expire", KEYS[1], ARGV[2])
        else
            return 0
        end
        """

        # Execute Lua script
        result = self.redis_client.eval(
            lua_script,
            1,
            lock_key,
            self.worker_id,
            self.LOCK_TTL_SECONDS
        )

        return result == 1

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

    def heartbeat_loop(self, engagement_id: str, stop_callback):
        """
        Run heartbeat loop to extend lock while processing

        Args:
            engagement_id: Engagement ID
            stop_callback: Function that returns True when processing is done
        """
        while not stop_callback():
            time.sleep(self.HEARTBEAT_INTERVAL_SECONDS)

            if not self.extend(engagement_id):
                # Failed to extend lock - another worker may have taken over
                print(f"WARNING: Failed to extend lock for engagement {engagement_id}")
                break


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
            raise Exception(
                f"Failed to acquire lock for engagement {self.engagement_id}. "
                f"Held by worker: {holder}"
            )

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Release lock on exit"""
        if self.acquired:
            self.lock.release(self.engagement_id)
