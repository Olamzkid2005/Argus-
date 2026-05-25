"""
Dead Letter Queue for failed Celery tasks

Stores failed tasks for later inspection and replay.
Uses Redis for temporary storage and PostgreSQL for persistence.
"""

import contextlib
import json
import logging
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import redis

from config.redis import REDIS_URL

logger = logging.getLogger(__name__)


@dataclass
class FailedTask:
    """Represents a failed task entry"""

    task_id: str
    task_name: str
    args: list
    kwargs: dict
    error_message: str
    error_class: str
    worker_id: str | None
    retry_count: int
    failed_at: str  # ISO 8601 string (serialized from datetime)
    engagement_id: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "FailedTask":
        """Deserialize from a JSON-loaded dict."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class DeadLetterQueue:
    """
    Manages failed tasks in a dead letter queue.

    Failed tasks are stored in Redis temporarily and can be
    persisted to PostgreSQL for long-term storage.
    """

    REDIS_KEY_PREFIX = "dlq:task"
    MAX_DLQ_SIZE = 1000

    def __init__(self, redis_url: str = None):
        self.redis_url = redis_url or REDIS_URL
        self._redis = None

    @property
    def redis(self) -> redis.Redis:
        """Lazy Redis connection"""
        if self._redis is None:
            self._redis = redis.from_url(self.redis_url)
        return self._redis

    def close(self):
        """Close the Redis connection explicitly."""
        if self._redis is not None:
            with contextlib.suppress(Exception):
                self._redis.close()
            self._redis = None

    @staticmethod
    def _sanitize_engagement_key(engagement_id: str) -> str:
        """Sanitize engagement_id for safe use in Redis keys.

        Prevents Redis key injection via malicious engagement_id values
        by stripping non-alphanumeric characters, newlines, colons, etc.

        Returns:
            Sanitized key component safe for Redis keys
        """
        from utils.validation import sanitize_redis_key
        return sanitize_redis_key(engagement_id)

    def enqueue(
        self,
        task_id: str,
        task_name: str,
        args: list,
        kwargs: dict,
        error_message: str,
        error_class: str,
        worker_id: str | None = None,
        retry_count: int = 0,
        engagement_id: str | None = None,
    ) -> bool:
        """
        Add a failed task to the dead letter queue.

        Args:
            task_id: Celery task ID
            task_name: Full task name (e.g., tasks.scan.run_scan)
            args: Task positional arguments
            kwargs: Task keyword arguments
            error_message: String representation of the exception
            error_class: Exception class name
            worker_id: Worker that processed the task
            retry_count: Number of retry attempts made
            engagement_id: Optional engagement ID for grouping

        Returns:
            True if successfully added to DLQ
        """
        try:
            failed_task = FailedTask(
                task_id=task_id,
                task_name=task_name,
                args=args,
                kwargs=kwargs,
                error_message=error_message,
                error_class=error_class,
                worker_id=worker_id,
                retry_count=retry_count,
                failed_at=datetime.now(UTC).isoformat(),
                engagement_id=engagement_id,
            )

            # Store in Redis sorted set by timestamp
            score = datetime.now(UTC).timestamp()
            key = f"{self.REDIS_KEY_PREFIX}:tasks"

            self.redis.zadd(key, {json.dumps(asdict(failed_task)): score})

            # Maintain secondary hash index for O(1) task-by-id lookups
            self.redis.hset(self.TASK_INDEX_KEY, task_id, json.dumps(asdict(failed_task)))

            # Trim to max size
            self.redis.zremrangebyrank(key, 0, -(self.MAX_DLQ_SIZE + 1))

            # Add to engagement-specific DLQ if applicable.
            # Store full task JSON (not just task_id) so engagement-filtered
            # retrieval doesn't need to scan the entire main key (bug #27).
            if engagement_id:
                safe_id = self._sanitize_engagement_key(engagement_id)
                eng_key = f"{self.REDIS_KEY_PREFIX}:engagement:{safe_id}"
                self.redis.zadd(eng_key, {json.dumps(asdict(failed_task)): score})
                self.redis.expire(eng_key, 86400 * 7)  # 7 days

            logger.warning(
                f"Task {task_id} ({task_name}) added to DLQ after {retry_count} retries"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to add task {task_id} to DLQ: {e}")
            return False

    def get_failed_tasks(
        self, engagement_id: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """
        Retrieve failed tasks from the DLQ.

        Args:
            engagement_id: Filter by engagement
            limit: Maximum number of tasks to return
            offset: Number of tasks to skip

        Returns:
            List of failed task dictionaries
        """
        try:
            if engagement_id:
                safe_id = self._sanitize_engagement_key(engagement_id)
                key = f"{self.REDIS_KEY_PREFIX}:engagement:{safe_id}"
                raw_tasks = self.redis.zrevrange(key, offset, offset + limit - 1)
                return [json.loads(t) for t in raw_tasks]
            else:
                key = f"{self.REDIS_KEY_PREFIX}:tasks"
                raw_tasks = self.redis.zrevrange(key, offset, offset + limit - 1)
                return [json.loads(t) for t in raw_tasks]

        except Exception as e:
            logger.error(f"Failed to retrieve DLQ tasks: {e}")
            return []

    def get_failed_task_count(self, engagement_id: str | None = None) -> int:
        """Get total number of failed tasks in DLQ"""
        try:
            if engagement_id:
                safe_id = self._sanitize_engagement_key(engagement_id)
                key = f"{self.REDIS_KEY_PREFIX}:engagement:{safe_id}"
                return self.redis.zcard(key)
            else:
                key = f"{self.REDIS_KEY_PREFIX}:tasks"
                return self.redis.zcard(key)
        except Exception as e:
            logger.error(f"Failed to get DLQ count: {e}")
            return 0

    TASK_INDEX_KEY = f"{REDIS_KEY_PREFIX}:index"  # Hash: task_id → JSON

    def get_task_by_id(self, task_id: str) -> dict | None:
        """
        Find a task in the DLQ by its ID using a secondary hash index.

        Args:
            task_id: The task ID to find

        Returns:
            Task dict if found, None otherwise
        """
        try:
            raw = self.redis.hget(self.TASK_INDEX_KEY, task_id)
            if raw:
                return json.loads(raw)
            return None
        except Exception as e:
            logger.error(f"Failed to look up task {task_id}: {e}")
            return None

    def purge(
        self, engagement_id: str | None = None, older_than_hours: int | None = None
    ) -> int:
        """
        Remove tasks from DLQ.

        Args:
            engagement_id: Purge only tasks for this engagement
            older_than_hours: Only purge tasks older than this

        Returns:
            Number of tasks removed
        """
        try:
            cutoff = None
            if older_than_hours:
                cutoff = datetime.now(UTC).timestamp() - (older_than_hours * 3600)

            if engagement_id and cutoff is not None:
                # Both filters: purge old tasks for a specific engagement.
                # Engagement-index key stores task_ids → iterate and check
                # timestamps against the main key.
                safe_id = self._sanitize_engagement_key(engagement_id)
                main_key = f"{self.REDIS_KEY_PREFIX}:tasks"
                eng_key = f"{self.REDIS_KEY_PREFIX}:engagement:{safe_id}"
                eng_task_ids = self.redis.zrangebyscore(eng_key, 0, cutoff)
                count = len(eng_task_ids)
                if count > 0:
                    # Remove from both the main key and the engagement index
                    for tid in eng_task_ids:
                        self.redis.zrem(main_key, tid)
                    self.redis.zremrangebyscore(eng_key, 0, cutoff)
                return count
            elif engagement_id:
                safe_id = self._sanitize_engagement_key(engagement_id)
                key = f"{self.REDIS_KEY_PREFIX}:engagement:{safe_id}"
                count = self.redis.zcard(key)
                self.redis.delete(key)
                return count
            elif cutoff is not None:
                key = f"{self.REDIS_KEY_PREFIX}:tasks"
                count = self.redis.zcount(key, 0, cutoff)
                self.redis.zremrangebyscore(key, 0, cutoff)
                # Best-effort index cleanup — remove stale entries
                try:
                    self.redis.delete(self.TASK_INDEX_KEY)
                except Exception:
                    logger.debug("Failed to clean up TASK_INDEX_KEY during purge", exc_info=True)
                return count
            else:
                key = f"{self.REDIS_KEY_PREFIX}:tasks"
                count = self.redis.zcard(key)
                self.redis.delete(key)
                self.redis.delete(self.TASK_INDEX_KEY)
                return count

        except Exception as e:
            logger.error(f"Failed to purge DLQ: {e}")
            return 0


# Singleton instance
_dlq: DeadLetterQueue | None = None
_dlq_lock = threading.Lock()


def get_dlq() -> DeadLetterQueue:
    """Get the singleton dead letter queue"""
    global _dlq
    if _dlq is None:
        with _dlq_lock:
            if _dlq is None:
                _dlq = DeadLetterQueue()
    return _dlq
