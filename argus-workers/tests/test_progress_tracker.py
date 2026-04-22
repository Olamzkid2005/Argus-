"""
Tests for tasks/progress_tracker.py

Validates: Progress tracking lifecycle, Redis integration, error handling
"""
import json
import pytest
from unittest.mock import Mock, patch, MagicMock

from tasks.progress_tracker import ProgressTracker, get_progress_tracker, PROGRESS_TTL


class TestProgressTracker:
    """Tests for ProgressTracker class"""

    @pytest.fixture
    def mock_redis(self):
        """Fixture providing a mock Redis client"""
        return MagicMock()

    @pytest.fixture
    def tracker(self, mock_redis):
        """Fixture providing a ProgressTracker with mocked Redis"""
        with patch("tasks.progress_tracker.redis.from_url", return_value=mock_redis):
            pt = ProgressTracker(redis_url="redis://mock:6379")
            # Force redis property to return our mock
            pt._redis = mock_redis
            yield pt

    def test_start_task(self, tracker, mock_redis):
        """Test starting a task creates correct progress record"""
        task_id = "task-123"
        engagement_id = "eng-456"
        task_name = "recon scan"
        total_steps = 50

        tracker.start_task(task_id, engagement_id, task_name, total_steps)

        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args[0]
        assert call_args[0] == f"task:progress:{task_id}"
        assert call_args[1] == PROGRESS_TTL

        data = json.loads(call_args[2])
        assert data["task_id"] == task_id
        assert data["engagement_id"] == engagement_id
        assert data["task_name"] == task_name
        assert data["status"] == "started"
        assert data["total_steps"] == total_steps
        assert data["current_step"] == 0
        assert data["percent_complete"] == 0
        assert data["current_activity"] == "Initializing..."
        assert "started_at" in data
        assert "updated_at" in data

    def test_update_progress(self, tracker, mock_redis):
        """Test updating progress modifies correct fields"""
        task_id = "task-123"
        existing = {
            "task_id": task_id,
            "engagement_id": "eng-456",
            "task_name": "recon",
            "status": "started",
            "total_steps": 100,
            "current_step": 0,
            "percent_complete": 0,
            "current_activity": "Initializing...",
        }
        mock_redis.get.return_value = json.dumps(existing)

        tracker.update_progress(task_id, current_step=25, activity="Scanning ports", metadata={"ports_found": 10})

        mock_redis.setex.assert_called_once()
        data = json.loads(mock_redis.setex.call_args[0][2])
        assert data["current_step"] == 25
        assert data["percent_complete"] == 25
        assert data["current_activity"] == "Scanning ports"
        assert data["metadata"] == {"ports_found": 10}
        assert "updated_at" in data

    def test_update_progress_no_record(self, tracker, mock_redis):
        """Test updating progress when no record exists logs warning and returns"""
        mock_redis.get.return_value = None

        tracker.update_progress("nonexistent", current_step=1)

        mock_redis.setex.assert_not_called()

    def test_update_progress_override_total(self, tracker, mock_redis):
        """Test update_progress can override total_steps"""
        existing = {
            "task_id": "task-123",
            "total_steps": 100,
            "current_step": 0,
        }
        mock_redis.get.return_value = json.dumps(existing)

        tracker.update_progress("task-123", current_step=50, total_steps=200)

        data = json.loads(mock_redis.setex.call_args[0][2])
        assert data["total_steps"] == 200
        assert data["percent_complete"] == 25

    def test_complete_task(self, tracker, mock_redis):
        """Test completing a task updates status and percent"""
        existing = {
            "task_id": "task-123",
            "status": "started",
            "total_steps": 100,
            "current_step": 50,
            "percent_complete": 50,
        }
        mock_redis.get.return_value = json.dumps(existing)

        tracker.complete_task("task-123", result={"findings": 5})

        data = json.loads(mock_redis.setex.call_args[0][2])
        assert data["status"] == "completed"
        assert data["current_step"] == 100
        assert data["percent_complete"] == 100
        assert data["current_activity"] == "Complete"
        assert "completed_at" in data
        assert data["result"] == {"findings": 5}

    def test_complete_task_no_record(self, tracker, mock_redis):
        """Test completing a task with no existing record"""
        mock_redis.get.return_value = None
        tracker.complete_task("nonexistent")
        mock_redis.setex.assert_not_called()

    def test_fail_task(self, tracker, mock_redis):
        """Test failing a task records error message"""
        existing = {
            "task_id": "task-123",
            "status": "started",
        }
        mock_redis.get.return_value = json.dumps(existing)

        tracker.fail_task("task-123", "Connection timeout")

        data = json.loads(mock_redis.setex.call_args[0][2])
        assert data["status"] == "failed"
        assert data["error_message"] == "Connection timeout"

    def test_fail_task_no_record(self, tracker, mock_redis):
        """Test failing a task with no existing record"""
        mock_redis.get.return_value = None
        tracker.fail_task("nonexistent", "error")
        mock_redis.setex.assert_not_called()

    def test_cancel_task(self, tracker, mock_redis):
        """Test cancelling a task updates status"""
        existing = {
            "task_id": "task-123",
            "status": "started",
        }
        mock_redis.get.return_value = json.dumps(existing)

        result = tracker.cancel_task("task-123")

        assert result is True
        data = json.loads(mock_redis.setex.call_args[0][2])
        assert data["status"] == "cancelled"

    def test_cancel_task_no_record(self, tracker, mock_redis):
        """Test cancelling a task with no existing record returns False"""
        mock_redis.get.return_value = None
        result = tracker.cancel_task("nonexistent")
        assert result is False

    def test_get_progress(self, tracker, mock_redis):
        """Test retrieving progress returns parsed dict"""
        expected = {"task_id": "task-123", "status": "started"}
        mock_redis.get.return_value = json.dumps(expected)

        result = tracker.get_progress("task-123")

        assert result == expected

    def test_get_progress_no_record(self, tracker, mock_redis):
        """Test retrieving progress for nonexistent task returns None"""
        mock_redis.get.return_value = None
        result = tracker.get_progress("nonexistent")
        assert result is None

    def test_update_progress_exception(self, tracker, mock_redis):
        """Test update_progress handles Redis exceptions gracefully"""
        mock_redis.get.side_effect = Exception("Redis error")
        tracker.update_progress("task-123", current_step=1)
        # Should not raise

    def test_complete_task_exception(self, tracker, mock_redis):
        """Test complete_task handles Redis exceptions gracefully"""
        mock_redis.get.side_effect = Exception("Redis error")
        tracker.complete_task("task-123")
        # Should not raise

    def test_fail_task_exception(self, tracker, mock_redis):
        """Test fail_task handles Redis exceptions gracefully"""
        mock_redis.get.side_effect = Exception("Redis error")
        tracker.fail_task("task-123", "error")
        # Should not raise

    def test_get_progress_exception(self, tracker, mock_redis):
        """Test get_progress handles Redis exceptions gracefully"""
        mock_redis.get.side_effect = Exception("Redis error")
        result = tracker.get_progress("task-123")
        assert result is None

    def test_cancel_task_exception(self, tracker, mock_redis):
        """Test cancel_task handles Redis exceptions gracefully"""
        mock_redis.get.side_effect = Exception("Redis error")
        result = tracker.cancel_task("task-123")
        assert result is False


class TestSingleton:
    """Tests for singleton accessor"""

    def test_get_progress_tracker_returns_same_instance(self):
        """Test get_progress_tracker returns a singleton"""
        pt1 = get_progress_tracker()
        pt2 = get_progress_tracker()
        assert pt1 is pt2

    def test_get_progress_tracker_returns_progress_tracker(self):
        """Test get_progress_tracker returns correct type"""
        pt = get_progress_tracker()
        assert isinstance(pt, ProgressTracker)
