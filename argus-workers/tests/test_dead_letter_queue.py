"""
Tests for dead_letter_queue.py
"""
import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from dead_letter_queue import DeadLetterQueue, FailedTask, get_dlq


class TestDeadLetterQueue:
    """Test suite for DeadLetterQueue"""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis connection"""
        with patch("dead_letter_queue.redis.from_url") as mock_from_url:
            mock_redis = MagicMock()
            mock_from_url.return_value = mock_redis
            yield mock_redis

    @pytest.fixture
    def dlq(self, mock_redis):
        return DeadLetterQueue(redis_url="redis://localhost:6379/0")

    def test_enqueue_success(self, dlq, mock_redis):
        """Test enqueueing a failed task"""
        result = dlq.enqueue(
            task_id="task-001",
            task_name="tasks.scan.run_scan",
            args=["ENG-001"],
            kwargs={"tool": "nuclei"},
            error_message="Connection timeout",
            error_class="TimeoutError",
            worker_id="worker-1",
            retry_count=3,
            engagement_id="ENG-001"
        )

        assert result is True
        mock_redis.zadd.assert_called()
        # Verify engagement-specific key was set
        mock_redis.expire.assert_called_once()

    def test_enqueue_without_engagement(self, dlq, mock_redis):
        """Test enqueueing without engagement_id"""
        result = dlq.enqueue(
            task_id="task-002",
            task_name="tasks.analyze.analyze",
            args=[],
            kwargs={},
            error_message="Error",
            error_class="ValueError",
        )

        assert result is True
        # Should not set engagement-specific key
        mock_redis.expire.assert_not_called()

    def test_enqueue_redis_error(self, dlq, mock_redis):
        """Test enqueue handles Redis errors"""
        mock_redis.zadd.side_effect = Exception("Redis connection lost")

        result = dlq.enqueue(
            task_id="task-003",
            task_name="tasks.scan.run_scan",
            args=[],
            kwargs={},
            error_message="Error",
            error_class="Exception",
        )

        assert result is False

    def test_enqueue_trims_to_max_size(self, dlq, mock_redis):
        """Test DLQ trims to max size"""
        dlq.enqueue(
            task_id="task-001",
            task_name="tasks.scan.run_scan",
            args=[],
            kwargs={},
            error_message="Error",
            error_class="Exception",
        )

        mock_redis.zremrangebyrank.assert_called_once_with(
            "dlq:task:tasks", 0, -(dlq.MAX_DLQ_SIZE + 1)
        )

    def test_get_failed_tasks_all(self, dlq, mock_redis):
        """Test retrieving all failed tasks"""
        task_data = {
            "task_id": "task-001",
            "task_name": "tasks.scan.run_scan",
            "args": [],
            "kwargs": {},
            "error_message": "timeout",
            "error_class": "TimeoutError",
            "worker_id": None,
            "retry_count": 2,
            "failed_at": datetime.now(UTC).isoformat(),
            "engagement_id": "ENG-001",
        }
        mock_redis.zrevrange.return_value = [json.dumps(task_data)]

        tasks = dlq.get_failed_tasks(limit=10)

        assert len(tasks) == 1
        assert tasks[0]["task_id"] == "task-001"
        mock_redis.zrevrange.assert_called_once_with("dlq:task:tasks", 0, 9)

    def test_get_failed_tasks_by_engagement(self, dlq, mock_redis):
        """Test retrieving failed tasks filtered by engagement"""
        task_data = {
            "task_id": "task-001",
            "task_name": "tasks.scan.run_scan",
            "args": [],
            "kwargs": {},
            "error_message": "timeout",
            "error_class": "TimeoutError",
            "worker_id": None,
            "retry_count": 2,
            "failed_at": datetime.now(UTC).isoformat(),
            "engagement_id": "ENG-001",
        }
        mock_redis.zrevrange.return_value = [b"task-001"]
        mock_redis.zrange.return_value = [json.dumps(task_data)]

        tasks = dlq.get_failed_tasks(engagement_id="ENG-001", limit=10)

        assert len(tasks) == 1
        assert tasks[0]["task_id"] == "task-001"

    def test_get_failed_tasks_redis_error(self, dlq, mock_redis):
        """Test get_failed_tasks handles Redis errors"""
        mock_redis.zrevrange.side_effect = Exception("Redis error")

        tasks = dlq.get_failed_tasks()

        assert tasks == []

    def test_get_failed_task_count_all(self, dlq, mock_redis):
        """Test getting total failed task count"""
        mock_redis.zcard.return_value = 42

        count = dlq.get_failed_task_count()

        assert count == 42
        mock_redis.zcard.assert_called_once_with("dlq:task:tasks")

    def test_get_failed_task_count_by_engagement(self, dlq, mock_redis):
        """Test getting count for specific engagement"""
        mock_redis.zcard.return_value = 5

        count = dlq.get_failed_task_count(engagement_id="ENG-001")

        assert count == 5
        mock_redis.zcard.assert_called_once_with("dlq:task:engagement:ENG-001")

    def test_replay_task_found(self, dlq, mock_redis):
        """Test replaying a failed task"""
        task_data = {
            "task_id": "task-001",
            "task_name": "tasks.scan.run_scan",
            "args": ["ENG-001"],
            "kwargs": {"tool": "nuclei"},
        }
        mock_redis.zrange.return_value = [json.dumps(task_data)]

        with patch("celery_app.app") as mock_app:
            result = dlq.replay_task("task-001")

        assert result is True
        mock_app.send_task.assert_called_once_with(
            "tasks.scan.run_scan",
            args=["ENG-001"],
            kwargs={"tool": "nuclei"},
            task_id="task-001.replay"
        )

    def test_replay_task_not_found(self, dlq, mock_redis):
        """Test replaying a task that doesn't exist"""
        mock_redis.zrange.return_value = []

        with patch("celery_app.app") as mock_app:
            result = dlq.replay_task("task-999")

        assert result is False
        mock_app.send_task.assert_not_called()

    def test_replay_task_error(self, dlq, mock_redis):
        """Test replay handles errors"""
        mock_redis.zrange.side_effect = Exception("Redis error")

        result = dlq.replay_task("task-001")
        assert result is False

    def test_purge_all(self, dlq, mock_redis):
        """Test purging all tasks"""
        mock_redis.zcard.return_value = 10

        count = dlq.purge()

        assert count == 10
        mock_redis.delete.assert_called_once_with("dlq:task:tasks")

    def test_purge_by_engagement(self, dlq, mock_redis):
        """Test purging tasks for specific engagement"""
        mock_redis.zcard.return_value = 3

        count = dlq.purge(engagement_id="ENG-001")

        assert count == 3
        mock_redis.delete.assert_called_once_with("dlq:task:engagement:ENG-001")

    def test_purge_older_than(self, dlq, mock_redis):
        """Test purging tasks older than specified hours"""
        mock_redis.zcount.return_value = 5

        count = dlq.purge(older_than_hours=24)

        assert count == 5
        mock_redis.zcount.assert_called_once()
        mock_redis.zremrangebyscore.assert_called_once()

    def test_purge_error(self, dlq, mock_redis):
        """Test purge handles errors"""
        mock_redis.zcard.side_effect = Exception("Redis error")

        count = dlq.purge()

        assert count == 0


class TestGetDLQ:
    """Test suite for the singleton get_dlq function"""

    def test_get_dlq_singleton(self):
        """Test get_dlq returns singleton instance"""
        with patch("dead_letter_queue.redis.from_url") as mock_from_url:
            mock_from_url.return_value = MagicMock()

            dlq1 = get_dlq()
            dlq2 = get_dlq()

            assert dlq1 is dlq2

    def test_failed_task_dataclass(self):
        """Test FailedTask dataclass creation"""
        task = FailedTask(
            task_id="task-001",
            task_name="tasks.scan.run_scan",
            args=["ENG-001"],
            kwargs={"tool": "nuclei"},
            error_message="timeout",
            error_class="TimeoutError",
            worker_id="worker-1",
            retry_count=2,
            failed_at=datetime.now(UTC).isoformat(),
            engagement_id="ENG-001",
        )

        assert task.task_id == "task-001"
        assert task.task_name == "tasks.scan.run_scan"
        assert task.engagement_id == "ENG-001"
