"""
Dead Letter Queue for failed Celery tasks

Stores failed tasks for later inspection and replay.
Uses Redis for temporary storage and PostgreSQL for persistence.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict

import redis

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")


@dataclass
class FailedTask:
    """Represents a failed task entry"""
    task_id: str
    task_name: str
    args: list
    kwargs: dict
    error_message: str
    error_class: str
    worker_id: Optional[str]
    retry_count: int
    failed_at: str
    engagement_id: Optional[str] = None


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
    
    def enqueue(
        self,
        task_id: str,
        task_name: str,
        args: list,
        kwargs: dict,
        error_message: str,
        error_class: str,
        worker_id: Optional[str] = None,
        retry_count: int = 0,
        engagement_id: Optional[str] = None
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
                failed_at=datetime.now(timezone.utc).isoformat(),
                engagement_id=engagement_id
            )
            
            # Store in Redis sorted set by timestamp
            score = datetime.now(timezone.utc).timestamp()
            key = f"{self.REDIS_KEY_PREFIX}:tasks"
            
            self.redis.zadd(key, {json.dumps(asdict(failed_task)): score})
            
            # Trim to max size
            self.redis.zremrangebyrank(key, 0, -(self.MAX_DLQ_SIZE + 1))
            
            # Add to engagement-specific DLQ if applicable
            if engagement_id:
                eng_key = f"{self.REDIS_KEY_PREFIX}:engagement:{engagement_id}"
                self.redis.zadd(eng_key, {task_id: score})
                self.redis.expire(eng_key, 86400 * 7)  # 7 days
            
            logger.warning(
                f"Task {task_id} ({task_name}) added to DLQ after {retry_count} retries"
            )
            return True
            
        except Exception as e:
            logger.error(f"Failed to add task {task_id} to DLQ: {e}")
            return False
    
    def get_failed_tasks(
        self,
        engagement_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
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
                key = f"{self.REDIS_KEY_PREFIX}:engagement:{engagement_id}"
                task_ids = self.redis.zrevrange(key, offset, offset + limit - 1)
                
                tasks = []
                main_key = f"{self.REDIS_KEY_PREFIX}:tasks"
                for raw_task in self.redis.zrange(main_key, 0, -1):
                    task = json.loads(raw_task)
                    if task["task_id"] in [tid.decode() if isinstance(tid, bytes) else tid for tid in task_ids]:
                        tasks.append(task)
                return tasks
            else:
                key = f"{self.REDIS_KEY_PREFIX}:tasks"
                raw_tasks = self.redis.zrevrange(key, offset, offset + limit - 1)
                return [json.loads(t) for t in raw_tasks]
                
        except Exception as e:
            logger.error(f"Failed to retrieve DLQ tasks: {e}")
            return []
    
    def get_failed_task_count(self, engagement_id: Optional[str] = None) -> int:
        """Get total number of failed tasks in DLQ"""
        try:
            if engagement_id:
                key = f"{self.REDIS_KEY_PREFIX}:engagement:{engagement_id}"
                return self.redis.zcard(key)
            else:
                key = f"{self.REDIS_KEY_PREFIX}:tasks"
                return self.redis.zcard(key)
        except Exception as e:
            logger.error(f"Failed to get DLQ count: {e}")
            return 0
    
    def replay_task(self, task_id: str) -> bool:
        """
        Replay a failed task by re-sending it to Celery.
        
        Args:
            task_id: The task ID to replay
            
        Returns:
            True if replay initiated successfully
        """
        try:
            # Find the task in DLQ
            key = f"{self.REDIS_KEY_PREFIX}:tasks"
            all_tasks = self.redis.zrange(key, 0, -1)
            
            for raw_task in all_tasks:
                task = json.loads(raw_task)
                if task["task_id"] == task_id:
                    # Send task back to Celery
                    from celery_app import app
                    app.send_task(
                        task["task_name"],
                        args=task["args"],
                        kwargs=task["kwargs"],
                        task_id=task_id + ".replay"
                    )
                    logger.info(f"Replayed task {task_id}")
                    return True
            
            logger.warning(f"Task {task_id} not found in DLQ")
            return False
            
        except Exception as e:
            logger.error(f"Failed to replay task {task_id}: {e}")
            return False
    
    def purge(self, engagement_id: Optional[str] = None, older_than_hours: Optional[int] = None) -> int:
        """
        Remove tasks from DLQ.
        
        Args:
            engagement_id: Purge only tasks for this engagement
            older_than_hours: Only purge tasks older than this
            
        Returns:
            Number of tasks removed
        """
        try:
            if engagement_id:
                key = f"{self.REDIS_KEY_PREFIX}:engagement:{engagement_id}"
                count = self.redis.zcard(key)
                self.redis.delete(key)
                return count
            elif older_than_hours:
                cutoff = datetime.now(timezone.utc).timestamp() - (older_than_hours * 3600)
                key = f"{self.REDIS_KEY_PREFIX}:tasks"
                count = self.redis.zcount(key, 0, cutoff)
                self.redis.zremrangebyscore(key, 0, cutoff)
                return count
            else:
                key = f"{self.REDIS_KEY_PREFIX}:tasks"
                count = self.redis.zcard(key)
                self.redis.delete(key)
                return count
                
        except Exception as e:
            logger.error(f"Failed to purge DLQ: {e}")
            return 0


# Singleton instance
_dlq: Optional[DeadLetterQueue] = None


def get_dlq() -> DeadLetterQueue:
    """Get the singleton dead letter queue"""
    global _dlq
    if _dlq is None:
        _dlq = DeadLetterQueue()
    return _dlq
