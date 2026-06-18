"""Tests for dispatch_task.py — task dispatching."""

import json
from unittest.mock import MagicMock, patch

import pytest

from dispatch_task import dispatch_task, main


class TestDispatchTask:
    def test_returns_dict_with_task_id_and_state(self):
        with patch("dispatch_task.app") as mock_app:
            mock_result = MagicMock()
            mock_result.id = "task-123"
            mock_result.state = "PENDING"
            mock_app.send_task.return_value = mock_result

            with patch.dict("os.environ", {"DATABASE_URL": "postgres://localhost"}):
                result = dispatch_task(
                    "some_task", ["arg1", "arg2"], task_id="custom-id"
                )
                assert result["task_id"] == "task-123"
                assert result["state"] == "PENDING"
                mock_app.send_task.assert_called_with(
                    "some_task",
                    args=["arg1", "arg2"],
                    task_id="custom-id",
                )

    def test_default_task_id(self):
        with patch("dispatch_task.app") as mock_app:
            mock_result = MagicMock()
            mock_result.id = "auto-id"
            mock_result.state = "PENDING"
            mock_app.send_task.return_value = mock_result

            with patch.dict("os.environ", {"DATABASE_URL": "postgres://localhost"}):
                result = dispatch_task("some_task", ["arg"])
                assert result["task_id"] == "auto-id"

    def test_respects_env(self):
        """dispatch_task should set PYTHONPATH."""
        with patch("dispatch_task.app") as mock_app:
            mock_result = MagicMock()
            mock_result.id = "t-1"
            mock_result.state = "PENDING"
            mock_app.send_task.return_value = mock_result

            with patch.dict(
                "os.environ", {"DATABASE_URL": "postgres://localhost"}, clear=True
            ):
                result = dispatch_task("task", ["arg"])
                assert result["task_id"] == "t-1"


class TestMain:
    def test_no_input_exits(self):
        with patch("sys.stdin.read", return_value=""):
            with pytest.raises(SystemExit):
                main()

    def test_invalid_json_exits(self):
        with patch("sys.stdin.read", return_value="not json"):
            with pytest.raises(SystemExit):
                main()

    def test_missing_type_exits(self):
        with patch("sys.stdin.read", return_value=json.dumps({"type": ""})):
            with pytest.raises(SystemExit):
                main()

    def test_unknown_type_exits(self):
        with patch("sys.stdin.read", return_value=json.dumps({"type": "unknown_type"})):
            with pytest.raises(SystemExit):
                main()

    def test_valid_job_dispatches(self):
        input_data = json.dumps(
            {
                "type": "recon",
                "engagement_id": "eng-1",
                "target": "https://example.com",
            }
        )
        with patch("sys.stdin.read", return_value=input_data):
            with patch("dispatch_task.dispatch_task") as mock_dispatch:
                mock_dispatch.return_value = {"task_id": "t-1", "state": "PENDING"}
                with patch("sys.stdout.write") as mock_write:
                    main()
                    mock_write.assert_called_once()
                    args = mock_write.call_args[0][0]
                    parsed = json.loads(args)
                    assert parsed["task_id"] == "t-1"
