"""
Dead Letter Queue for failed Celery tasks

Stores failed tasks for later inspection and replay.
Uses Redis for temporary storage and PostgreSQL for persistence.
"""

import contextlib
import json
import logging
import re
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import redis
from typing import cast, Any as TAny

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
        # At this point _redis is always set — help mypy narrow the type
        assert self._redis is not None
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

    # Patterns matching common API keys, tokens, and secrets in string values (M-v3-08)
    _SECRET_VALUE_PATTERNS: list[re.Pattern] = [
        re.compile(r"^sk-or-v1-[a-zA-Z0-9]{20,}$"),  # OpenRouter API key
        re.compile(r"^sk-[a-zA-Z0-9]{20,}$"),  # OpenAI API key
        re.compile(r"^gh[pso]_[a-zA-Z0-9]{36,}$"),  # GitHub token (pat/oauth/secret)
        re.compile(r"^ghr_[a-zA-Z0-9]{36,}$"),  # GitHub refresh token
        re.compile(r"^xox[bpsa]-[a-zA-Z0-9-]{20,}$"),  # Slack token
        re.compile(r"^AKIA[0-9A-Z]{16}$"),  # AWS access key
        re.compile(r"^(eyJ[a-zA-Z0-9_-]{10,}\.)"),  # JWT token
        re.compile(r"^[a-f0-9]{64,}$", re.IGNORECASE),  # SHA-256 hex (64+ chars)
    ]

    @staticmethod
    def _looks_like_secret(value: str) -> bool:
        """Check if a string value matches known secret patterns."""
        for pattern in DeadLetterQueue._SECRET_VALUE_PATTERNS:
            if pattern.match(value):
                return True
        return False

    @staticmethod
    def _redact_sensitive_fields(data: Any) -> Any:
        """Recursively redact sensitive fields from arbitrary data structures.

        Handles:
        - Dict keys matching sensitive names (substring match)
        - Nested dicts (recursive)
        - Lists containing dicts
        - String values matching secret patterns (API keys, tokens, JWTs)
        - Mixed nested structures (dicts within lists within dicts, etc.)

        H-v3-22: Basic key-based redaction.
        M-v3-08: Added list traversal and pattern-based value redaction.
        """
        SENSITIVE_KEYS = {
            "password",
            "passwd",
            "token",
            "secret",
            "api_key",
            "auth",
            "credentials",
            "cookie",
            "totp_secret",
            "two_factor_secret",
            "private_key",
            "access_key",
            "session_id",
            "refresh_token",
        }

        if isinstance(data, dict):
            redacted = {}
            for key, value in data.items():
                if any(s in key.lower() for s in SENSITIVE_KEYS):
                    redacted[key] = "__REDACTED__"
                elif isinstance(value, (dict, list)):
                    redacted[key] = DeadLetterQueue._redact_sensitive_fields(value)
                elif isinstance(value, str) and DeadLetterQueue._looks_like_secret(
                    value
                ):
                    redacted[key] = "__REDACTED__"
                else:
                    redacted[key] = value
            return redacted
        elif isinstance(data, list):
            return [DeadLetterQueue._redact_sensitive_fields(item) for item in data]
        else:
            return data

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

        Credential fields in kwargs are redacted before storage (H-v3-22).

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
            # Redact sensitive fields from both args and kwargs (H-v3-22, M-v3-08)
            safe_kwargs = self._redact_sensitive_fields(kwargs)
            safe_args = self._redact_sensitive_fields(args)

            # Redact secret patterns in error_message (H-09)
            safe_error = error_message
            for pattern in self._SECRET_VALUE_PATTERNS:
                safe_error = pattern.sub("__REDACTED__", safe_error)

            failed_task = FailedTask(
                task_id=task_id,
                task_name=task_name,
                args=safe_args,
                kwargs=safe_kwargs,
                error_message=safe_error,
                error_class=error_class,
                worker_id=worker_id,
                retry_count=retry_count,
                failed_at=datetime.now(UTC).isoformat(),
                engagement_id=engagement_id,
            )

            # Store in Redis sorted set by timestamp.
            # Use task_id as the sorted set member (not full JSON) so that
            # cross-key operations (purge, cleanup) always match correctly
            # regardless of JSON serialization ordering (C3).
            score = datetime.now(UTC).timestamp()
            task_json = json.dumps(asdict(failed_task))
            key = f"{self.REDIS_KEY_PREFIX}:tasks"

            self.redis.zadd(key, {task_id: score})
            # Auto-expiry for main DLQ (M-v3-08): prevent unbounded growth
            self.redis.expire(key, 86400 * 7)

            # Maintain secondary hash index for O(1) task-by-id lookups
            # AND as the canonical JSON data store (the sorted sets hold only IDs)
            self.redis.hset(self.TASK_INDEX_KEY, task_id, task_json)
            self.redis.expire(self.TASK_INDEX_KEY, 86400 * 7)

            # Trim to max size (based on main key)
            self.redis.zremrangebyrank(key, 0, -(self.MAX_DLQ_SIZE + 1))

            # Add to engagement-specific DLQ if applicable.
            # Store task_id (not full JSON) as member for consistent cross-key operations.
            if engagement_id:
                safe_id = self._sanitize_engagement_key(engagement_id)
                eng_key = f"{self.REDIS_KEY_PREFIX}:engagement:{safe_id}"
                self.redis.zadd(eng_key, {task_id: score})
                self.redis.expire(eng_key, 86400 * 7)  # 7 days

            logger.warning(
                "Task %s (%s) added to DLQ after %d retries",
                task_id,
                task_name,
                retry_count,
            )
            return True

        except Exception as e:
            logger.error("Failed to add task %s to DLQ: %s", task_id, e)
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
                raw_ids = self.redis.zrevrange(key, offset, offset + limit - 1)
                task_ids: list[bytes] = cast(list[bytes], raw_ids)
            else:
                key = f"{self.REDIS_KEY_PREFIX}:tasks"
                raw_ids = self.redis.zrevrange(key, offset, offset + limit - 1)
                task_ids = cast(list[bytes], raw_ids)

            if not task_ids:
                return []

            # Look up full task data from the index hash (sorted sets hold only IDs)
            decoded_ids = [
                tid.decode("utf-8") if isinstance(tid, bytes) else tid
                for tid in task_ids
            ]
            raw_data = cast(list[bytes | None], self.redis.hmget(self.TASK_INDEX_KEY, decoded_ids))
            tasks = []
            for raw in raw_data:
                if raw:
                    try:
                        tasks.append(json.loads(raw))
                    except (json.JSONDecodeError, TypeError):
                        logger.debug(
                            "Failed to decode DLQ task data for ID", exc_info=True
                        )
            return tasks

        except Exception as e:
            logger.error("Failed to retrieve DLQ tasks: %s", e)
            return []

    def get_failed_task_count(self, engagement_id: str | None = None) -> int:
        """Get total number of failed tasks in DLQ"""
        try:
            if engagement_id:
                safe_id = self._sanitize_engagement_key(engagement_id)
                key = f"{self.REDIS_KEY_PREFIX}:engagement:{safe_id}"
                return cast(int, self.redis.zcard(key))
            else:
                key = f"{self.REDIS_KEY_PREFIX}:tasks"
                return cast(int, self.redis.zcard(key))
        except Exception as e:
            logger.error("Failed to get DLQ count: %s", e)
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
            raw = cast(bytes | None, self.redis.hget(self.TASK_INDEX_KEY, task_id))
            if raw:
                return json.loads(raw)
            return None
        except Exception as e:
            logger.error("Failed to look up task %s: %s", task_id, e)
            return None

    def _remove_from_index(self, task_ids: list[str]) -> None:
        """Remove specific task IDs from the secondary hash index.

        Unlike the old approach of deleting the entire TASK_INDEX_KEY (M4),
        this selectively removes only the purged entries so that lookups
        via get_task_by_id() continue to work for non-purged tasks.
        """
        if not task_ids:
            return
        try:
            self.redis.hdel(self.TASK_INDEX_KEY, *cast(list[TAny], task_ids))
        except Exception:
            logger.debug("Failed to selectively clean TASK_INDEX_KEY", exc_info=True)

    # ── Postgres-backed DLQ fallback (Phase 4.5.1) ──
    # When Redis is unavailable, tasks are persisted directly to PostgreSQL
    # in the dead_letter_queue table. This ensures no tasks are lost during
    # Redis outages or when the shutdown deadline is exceeded.

    def _persist_to_postgres(self, task: FailedTask) -> bool:
        """Persist a failed task to PostgreSQL.

        Saves to the dead_letter_queue table with full task metadata.
        Idempotent: uses ON CONFLICT DO NOTHING so retries don't duplicate.

        Returns:
            True if persisted successfully (or already exists).
        """
        try:
            from database.connection import get_db

            db = get_db()
            conn = db.get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO dead_letter_queue (
                        task_id, task_name, args, kwargs,
                        error_message, error_class, worker_id,
                        retry_count, failed_at, engagement_id
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    ) ON CONFLICT (task_id) DO NOTHING
                    """,
                    (
                        task.task_id,
                        task.task_name,
                        json.dumps(task.args),
                        json.dumps(task.kwargs),
                        task.error_message,
                        task.error_class,
                        task.worker_id,
                        task.retry_count,
                        task.failed_at,
                        task.engagement_id,
                    ),
                )
                conn.commit()
                return True
            finally:
                cursor.close()
                db.release_connection(conn)
        except Exception as e:
            logger.error("Failed to persist task %s to PG DLQ: %s", task.task_id, e)
            return False

    def flush_to_postgres(self, max_tasks: int = 100) -> int:
        """Flush pending Redis DLQ entries to PostgreSQL.

        Phase 4.5.1 + 4.5.2: Called during shutdown to persist all pending
        failed tasks before force-exit. Also callable periodically for backup.

        Args:
            max_tasks: Maximum tasks to flush (default 100).

        Returns:
            Number of tasks flushed.
        """
        try:
            tasks = self.get_failed_tasks(limit=max_tasks)
            if not tasks:
                return 0

            flushed = 0
            for task_data in tasks:
                try:
                    failed_task = FailedTask.from_dict(task_data)
                    if self._persist_to_postgres(failed_task):
                        flushed += 1
                except Exception as e:
                    logger.warning("Failed to flush DLQ entry: %s", e)

            logger.info("Flushed %d/%d DLQ entries to PostgreSQL", flushed, len(tasks))
            return flushed
        except Exception as e:
            logger.error("Failed to flush DLQ to PG: %s", e)
            return 0

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

            main_key = f"{self.REDIS_KEY_PREFIX}:tasks"

            if engagement_id and cutoff is not None:
                # Both filters: purge old tasks for a specific engagement.
                safe_id = self._sanitize_engagement_key(engagement_id)
                eng_key = f"{self.REDIS_KEY_PREFIX}:engagement:{safe_id}"
                eng_task_ids = cast(list[bytes], self.redis.zrangebyscore(eng_key, 0, cutoff))
                count = len(eng_task_ids)
                if count > 0:
                    decoded = [
                        tid.decode("utf-8") if isinstance(tid, bytes) else tid
                        for tid in eng_task_ids
                    ]
                    for tid in eng_task_ids:
                        self.redis.zrem(main_key, tid)
                    self.redis.zremrangebyscore(eng_key, 0, cutoff)
                    self._remove_from_index(decoded)
                return count
            elif engagement_id:
                safe_id = self._sanitize_engagement_key(engagement_id)
                eng_key = f"{self.REDIS_KEY_PREFIX}:engagement:{safe_id}"
                all_ids = cast(list[bytes], self.redis.zrange(eng_key, 0, -1))
                decoded_ids = [
                    tid.decode("utf-8") if isinstance(tid, bytes) else tid
                    for tid in all_ids
                ]
                count = cast(int, self.redis.zcard(eng_key))
                self.redis.delete(eng_key)
                for tid in all_ids:
                    self.redis.zrem(main_key, tid)
                self._remove_from_index(decoded_ids)
                return count
            elif cutoff is not None:
                task_ids = cast(list[bytes], self.redis.zrangebyscore(main_key, 0, cutoff))
                decoded_ids = [
                    tid.decode("utf-8") if isinstance(tid, bytes) else tid
                    for tid in task_ids
                ]
                count = len(decoded_ids)
                self.redis.zremrangebyscore(main_key, 0, cutoff)
                self._remove_from_index(decoded_ids)
                return count
            else:
                count = cast(int, self.redis.zcard(main_key))
                self.redis.delete(main_key)
                self.redis.delete(self.TASK_INDEX_KEY)
                return count

        except Exception as e:
            logger.error("Failed to purge DLQ: %s", e)
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
