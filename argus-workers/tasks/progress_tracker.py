"""
Long-running task progress tracking

Tracks progress of Celery tasks and stores in Redis for frontend polling.
"""

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

import redis

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
PROGRESS_TTL = 86400  # 24 hours


class ProgressTracker:
    """
    Tracks progress of long-running tasks.

    Stores progress in Redis for real-time frontend access.
    """

    REDIS_PREFIX = "task:progress"

    def __init__(self, redis_url: str = None):
        self.redis_url = redis_url or REDIS_URL
        self._redis = None

    @property
    def redis(self) -> redis.Redis:
        """Lazy Redis connection"""
        if self._redis is None:
            self._redis = redis.from_url(self.redis_url)
        return self._redis

    def _get_key(self, task_id: str) -> str:
        return f"{self.REDIS_PREFIX}:{task_id}"

    def start_task(
        self,
        task_id: str,
        engagement_id: str,
        task_name: str,
        total_steps: int = 100
    ):
        """
        Initialize progress tracking for a task.

        Args:
            task_id: Celery task ID
            engagement_id: Engagement ID
            task_name: Human-readable task name
            total_steps: Total number of steps in task
        """
        data = {
            "task_id": task_id,
            "engagement_id": engagement_id,
            "task_name": task_name,
            "status": "started",
            "total_steps": total_steps,
            "current_step": 0,
            "percent_complete": 0,
            "current_activity": "Initializing...",
            "started_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        }

        key = self._get_key(task_id)
        self.redis.setex(key, PROGRESS_TTL, json.dumps(data))
        logger.info(f"Progress tracking started for task {task_id}")

    def update_progress(
        self,
        task_id: str,
        current_step: int,
        total_steps: int | None = None,
        activity: str | None = None,
        metadata: dict[str, Any] | None = None
    ):
        """
        Update task progress.

        Args:
            task_id: Celery task ID
            current_step: Current step number
            total_steps: Optional override of total steps
            activity: Current activity description
            metadata: Additional data (findings count, etc.)
        """
        key = self._get_key(task_id)

        try:
            existing = self.redis.get(key)
            if not existing:
                logger.warning(f"No progress record for task {task_id}")
                return

            data = json.loads(existing)
            data["current_step"] = current_step

            if total_steps:
                data["total_steps"] = total_steps

            if activity:
                data["current_activity"] = activity

            if metadata:
                data["metadata"] = metadata

            data["percent_complete"] = min(100, int(
                (current_step / data["total_steps"]) * 100
            ))
            data["updated_at"] = datetime.now(UTC).isoformat()

            self.redis.setex(key, PROGRESS_TTL, json.dumps(data))

        except Exception as e:
            logger.error(f"Failed to update progress for {task_id}: {e}")

    def complete_task(self, task_id: str, result: dict | None = None):
        """Mark task as complete"""
        key = self._get_key(task_id)

        try:
            existing = self.redis.get(key)
            if existing:
                data = json.loads(existing)
                data["status"] = "completed"
                data["current_step"] = data["total_steps"]
                data["percent_complete"] = 100
                data["current_activity"] = "Complete"
                data["completed_at"] = datetime.now(UTC).isoformat()
                data["updated_at"] = data["completed_at"]

                if result:
                    data["result"] = result

                self.redis.setex(key, PROGRESS_TTL, json.dumps(data))

        except Exception as e:
            logger.error(f"Failed to complete progress for {task_id}: {e}")

    def fail_task(self, task_id: str, error_message: str):
        """Mark task as failed"""
        key = self._get_key(task_id)

        try:
            existing = self.redis.get(key)
            if existing:
                data = json.loads(existing)
                data["status"] = "failed"
                data["error_message"] = error_message
                data["updated_at"] = datetime.now(UTC).isoformat()

                self.redis.setex(key, PROGRESS_TTL, json.dumps(data))

        except Exception as e:
            logger.error(f"Failed to fail progress for {task_id}: {e}")

    def get_progress(self, task_id: str) -> dict[str, Any] | None:
        """Get current progress for a task"""
        key = self._get_key(task_id)

        try:
            data = self.redis.get(key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.error(f"Failed to get progress for {task_id}: {e}")

        return None

    def cancel_task(self, task_id: str) -> bool:
        """
        Mark task as cancelled.

        Note: Actual task cancellation must be done via Celery revoke.
        This just updates the progress record.
        """
        key = self._get_key(task_id)

        try:
            existing = self.redis.get(key)
            if existing:
                data = json.loads(existing)
                data["status"] = "cancelled"
                data["updated_at"] = datetime.now(UTC).isoformat()

                self.redis.setex(key, PROGRESS_TTL, json.dumps(data))
                return True
        except Exception as e:
            logger.error(f"Failed to cancel progress for {task_id}: {e}")

        return False


# Singleton instance
_progress_tracker: ProgressTracker | None = None


def get_progress_tracker() -> ProgressTracker:
    """Get singleton progress tracker"""
    global _progress_tracker
    if _progress_tracker is None:
        _progress_tracker = ProgressTracker()
    return _progress_tracker
