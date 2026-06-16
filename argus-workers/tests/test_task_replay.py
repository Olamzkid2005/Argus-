"""
Tests for tasks/replay.py — Dead Letter Queue task replay.
"""

from unittest.mock import MagicMock, patch

from tasks.replay import replay_dlq_task


class TestReplayDlqTask:
    """Test suite for replay_dlq_task"""

    @patch("tasks.replay.get_dlq")
    @patch("tasks.replay.app")
    def test_returns_false_when_task_not_in_dlq(self, mock_app, mock_get_dlq):  # noqa: ARG002
        mock_dlq = MagicMock()
        mock_dlq.get_task_by_id.return_value = None
        mock_get_dlq.return_value = mock_dlq

        result = replay_dlq_task.run(task_id="missing-task")

        assert result is False
        mock_dlq.get_task_by_id.assert_called_once_with("missing-task")

    @patch("tasks.replay.get_dlq")
    @patch("tasks.replay.app")
    def test_sends_task_to_celery_and_returns_true(self, mock_app, mock_get_dlq):
        mock_dlq = MagicMock()
        mock_dlq.get_task_by_id.return_value = {
            "task_name": "tasks.scan.run_scan",
            "args": ["ENG-001"],
            "kwargs": {"tool": "nuclei"},
        }
        mock_get_dlq.return_value = mock_dlq

        result = replay_dlq_task.run(task_id="task-001")

        assert result is True
        mock_app.send_task.assert_called_once_with(
            "tasks.scan.run_scan",
            args=["ENG-001"],
            kwargs={"tool": "nuclei"},
            task_id="task-001.replay",
        )

    @patch("tasks.replay.get_dlq")
    @patch("tasks.replay.app")
    def test_returns_false_when_send_task_fails(self, mock_app, mock_get_dlq):
        mock_dlq = MagicMock()
        mock_dlq.get_task_by_id.return_value = {
            "task_name": "tasks.scan.run_scan",
            "args": [],
            "kwargs": {},
        }
        mock_get_dlq.return_value = mock_dlq
        mock_app.send_task.side_effect = RuntimeError("broker unavailable")

        result = replay_dlq_task.run(task_id="task-002")

        assert result is False
        mock_app.send_task.assert_called_once()
