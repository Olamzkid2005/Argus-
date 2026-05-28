"""
Progress tracker for Celery tasks.

Tracks task progress in Redis for real-time frontend updates.
Restored from M-05 dead code removal — still used by tests.
"""

import json
import logging
from datetime import datetime
from typing import Any

import redis as _redis_module

logger = logging.getLogger(__name__)

redis = _redis_module  # Module-level reference for test patching
PROGRESS_TTL = 3600  # 1 hour


class ProgressTracker:
    """Tracks task progress in Redis."""

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self._redis = None
        self._redis_url = redis_url

    @property
    def redis(self):
        if self._redis is None:
            self._redis = redis.from_url(self._redis_url)
        return self._redis

    def start_task(
        self,
        task_id: str,
        engagement_id: str,
        task_name: str,
        total_steps: int = 100,
    ) -> None:
        """Record a new task as started."""
        data = {
            "task_id": task_id,
            "engagement_id": engagement_id,
            "task_name": task_name,
            "status": "started",
            "total_steps": total_steps,
            "current_step": 0,
            "percent_complete": 0,
            "current_activity": "Initializing...",
            "started_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
        self.redis.setex(f"task:progress:{task_id}", PROGRESS_TTL, json.dumps(data))

    def update_progress(
        self,
        task_id: str,
        current_step: int | None = None,
        total_steps: int | None = None,
        activity: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Update an existing task's progress."""
        try:
            raw = self.redis.get(f"task:progress:{task_id}")
            if not raw:
                logger.warning("No progress record found for task %s", task_id)
                return
            data = json.loads(raw)
            if current_step is not None:
                data["current_step"] = current_step
            if total_steps is not None:
                data["total_steps"] = total_steps
            if data.get("total_steps", 1) > 0:
                data["percent_complete"] = int(
                    (data.get("current_step", 0) / data["total_steps"]) * 100
                )
            if activity is not None:
                data["current_activity"] = activity
            if metadata is not None:
                data.setdefault("metadata", {}).update(metadata)
            data["updated_at"] = datetime.utcnow().isoformat()
            self.redis.setex(f"task:progress:{task_id}", PROGRESS_TTL, json.dumps(data))
        except Exception:
            logger.exception("Failed to update progress for task %s", task_id)

    def complete_task(self, task_id: str, result: dict | None = None) -> None:
        """Mark a task as completed."""
        try:
            raw = self.redis.get(f"task:progress:{task_id}")
            if not raw:
                logger.warning("No progress record found for task %s", task_id)
                return
            data = json.loads(raw)
            data["status"] = "completed"
            data["current_step"] = data.get("total_steps", 100)
            data["percent_complete"] = 100
            data["current_activity"] = "Complete"
            data["completed_at"] = datetime.utcnow().isoformat()
            if result:
                data["result"] = result
            data["updated_at"] = datetime.utcnow().isoformat()
            self.redis.setex(f"task:progress:{task_id}", PROGRESS_TTL, json.dumps(data))
        except Exception:
            logger.exception("Failed to complete task %s", task_id)

    def fail_task(self, task_id: str, error_message: str) -> None:
        """Mark a task as failed."""
        try:
            raw = self.redis.get(f"task:progress:{task_id}")
            if not raw:
                logger.warning("No progress record found for task %s", task_id)
                return
            data = json.loads(raw)
            data["status"] = "failed"
            data["error_message"] = error_message
            data["updated_at"] = datetime.utcnow().isoformat()
            self.redis.setex(f"task:progress:{task_id}", PROGRESS_TTL, json.dumps(data))
        except Exception:
            logger.exception("Failed to fail task %s", task_id)

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a running task. Returns False if no record exists."""
        try:
            raw = self.redis.get(f"task:progress:{task_id}")
            if not raw:
                return False
            data = json.loads(raw)
            data["status"] = "cancelled"
            data["updated_at"] = datetime.utcnow().isoformat()
            self.redis.setex(f"task:progress:{task_id}", PROGRESS_TTL, json.dumps(data))
            return True
        except Exception:
            logger.exception("Failed to cancel task %s", task_id)
            return False

    def get_progress(self, task_id: str) -> dict[str, Any] | None:
        """Get current progress for a task."""
        try:
            raw = self.redis.get(f"task:progress:{task_id}")
            if raw:
                return json.loads(raw)
            return None
        except Exception:
            logger.exception("Failed to get progress for task %s", task_id)
            return None


_instance: ProgressTracker | None = None


def get_progress_tracker() -> ProgressTracker:
    """Get the singleton ProgressTracker instance."""
    global _instance
    if _instance is None:
        _instance = ProgressTracker()
    return _instance
