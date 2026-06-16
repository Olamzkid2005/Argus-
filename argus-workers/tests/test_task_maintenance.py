"""Tests for tasks.maintenance — Celery maintenance tasks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tasks.maintenance import (
    cleanup_checkpoints as _cleanup_checkpoints_task,
)
from tasks.maintenance import (
    cleanup_failed_engagements as _cleanup_failed_engagements_task,
)
from tasks.maintenance import (
    cleanup_old_results as _cleanup_old_results_task,
)
from tasks.maintenance import (
    worker_health_check as _worker_health_check_task,
)

# Call the original unwrapped function to avoid Celery auto-retry wrapper
cleanup_old_results = _cleanup_old_results_task._orig_run
cleanup_failed_engagements = _cleanup_failed_engagements_task._orig_run
cleanup_checkpoints = _cleanup_checkpoints_task._orig_run
worker_health_check = _worker_health_check_task._orig_run


@pytest.fixture(autouse=True)
def mock_db():
    with patch("tasks.maintenance.db_cursor") as mock_db_cursor:
        mock_cm = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 5
        mock_cm.__enter__.return_value = mock_cursor
        mock_db_cursor.return_value = mock_cm
        yield mock_cursor


class TestCleanupOldResults:
    """Tests for cleanup_old_results()."""

    def test_deletes_old_records_and_returns_counts(self):
        result = cleanup_old_results()

        assert result["status"] == "completed"
        assert result["snapshots_deleted"] == 5
        assert result["checkpoints_deleted"] == 5
        assert result["raw_outputs_deleted"] == 5
        assert result["perf_logs_deleted"] == 5

    @patch("tasks.maintenance.db_cursor")
    def test_handles_errors_gracefully(self, mock_db_cursor):
        mock_db_cursor.side_effect = Exception("DB is down")
        result = cleanup_old_results()

        assert result["status"] == "error"
        assert "DB is down" in result["error"]


class TestCleanupFailedEngagements:
    """Tests for cleanup_failed_engagements()."""

    def test_deletes_stale_engagement_data(self):
        result = cleanup_failed_engagements()

        assert result["status"] == "completed"
        assert result["states_deleted"] == 5
        assert result["budgets_deleted"] == 5
        assert result["activities_deleted"] == 5
        assert result["findings_deleted"] == 5
        assert result["engagements_deleted"] == 5

    @patch("tasks.maintenance.db_cursor")
    def test_handles_errors_gracefully(self, mock_db_cursor):
        mock_db_cursor.side_effect = Exception("Connection refused")
        result = cleanup_failed_engagements()

        assert result["status"] == "error"
        assert "Connection refused" in result["error"]


class TestCleanupCheckpoints:
    """Tests for cleanup_checkpoints()."""

    def test_applies_different_retention_for_active_vs_completed(self, mock_db):
        def _fake_execute(sql, *args, **kwargs):
            return None

        mock_db.execute.side_effect = _fake_execute

        result = cleanup_checkpoints()

        assert result["status"] == "completed"
        assert result["active_engagement_checkpoints_deleted"] == 5
        assert result["completed_engagement_checkpoints_deleted"] == 5

    @patch("tasks.maintenance.db_cursor")
    def test_handles_errors_gracefully(self, mock_db_cursor):
        mock_db_cursor.side_effect = Exception("Timeout")
        result = cleanup_checkpoints()

        assert result["status"] == "error"
        assert "Timeout" in result["error"]


class TestWorkerHealthCheck:
    """Tests for worker_health_check()."""

    def test_returns_status_ok_with_hostname(self):
        result = worker_health_check()

        assert result["status"] == "ok"
        assert isinstance(result["hostname"], str)
        assert isinstance(result["timestamp"], str)
