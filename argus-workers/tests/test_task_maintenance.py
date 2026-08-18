"""Tests for tasks.maintenance — Celery maintenance tasks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tasks.maintenance import (
    cleanup_checkpoints as _cleanup_checkpoints_task,
)
from tasks.maintenance import (
    cleanup_dlq as _cleanup_dlq_task,
)
from tasks.maintenance import (
    cleanup_failed_engagements as _cleanup_failed_engagements_task,
)
from tasks.maintenance import (
    cleanup_old_results as _cleanup_old_results_task,
)
from tasks.maintenance import (
    refresh_views as _refresh_views_task,
)
from tasks.maintenance import (
    update_nuclei_templates as _update_nuclei_templates_task,
)
from tasks.maintenance import (
    worker_health_check as _worker_health_check_task,
)

# Call the original unwrapped function to avoid Celery auto-retry wrapper
cleanup_old_results = _cleanup_old_results_task._orig_run
cleanup_failed_engagements = _cleanup_failed_engagements_task._orig_run
cleanup_checkpoints = _cleanup_checkpoints_task._orig_run
cleanup_dlq = _cleanup_dlq_task._orig_run
refresh_views = _refresh_views_task._orig_run
update_nuclei_templates = _update_nuclei_templates_task._orig_run
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


# ---------------------------------------------------------------------------
# refresh_views
# ---------------------------------------------------------------------------


class TestRefreshViews:
    """Tests for refresh_views()."""

    @patch("database.connection.get_db")
    def test_refreshes_all_views_concurrently(self, mock_get_db):
        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db.get_connection.return_value = mock_conn
        mock_get_db.return_value = mock_db
        # conn.cursor() must return the same mock_cursor the code uses
        mock_conn.cursor.return_value = mock_cursor

        # Capture autocommit state during execution
        autocommit_during: list[bool] = []

        def _capture_execute(sql):
            autocommit_during.append(mock_conn.autocommit)

        mock_cursor.execute.side_effect = _capture_execute

        result = refresh_views()

        assert result["status"] == "completed"
        assert result["refreshed"] == [
            "mv_org_dashboard",
            "mv_engagement_findings",
            "mv_tool_performance",
        ]
        assert result["errors"] == []
        # Autocommit must be True during refresh (CONCURRENTLY requirement)
        assert all(autocommit_during)
        # autocommit restored to False after
        assert mock_conn.autocommit is False

    @patch("database.connection.get_db")
    def test_reports_individual_view_failure(self, mock_get_db):
        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db.get_connection.return_value = mock_conn
        mock_get_db.return_value = mock_db
        # conn.cursor() must return the same mock_cursor the code uses
        mock_conn.cursor.return_value = mock_cursor

        # Second view fails
        mock_cursor.execute.side_effect = [
            None,
            Exception("concurrent update detected"),
            None,
        ]

        result = refresh_views()

        assert result["status"] == "completed"
        assert result["refreshed"] == [
            "mv_org_dashboard",
            "mv_tool_performance",
        ]
        assert len(result["errors"]) == 1
        assert result["errors"][0]["view"] == "mv_engagement_findings"
        assert "concurrent update" in result["errors"][0]["error"]

    @patch("database.connection.get_db")
    def test_handles_db_failure(self, mock_get_db):
        mock_get_db.side_effect = Exception("connection refused")
        result = refresh_views()

        assert result["status"] == "error"
        assert "connection refused" in result["error"]


# ---------------------------------------------------------------------------
# update_nuclei_templates
# ---------------------------------------------------------------------------


class TestUpdateNucleiTemplates:
    """Tests for update_nuclei_templates()."""

    @patch(
        "tools.update_nuclei_templates.update_nuclei_templates",
        return_value=True,
    )
    @patch(
        "tools.update_nuclei_templates.get_template_count",
        side_effect=[5, 9],
    )
    def test_updates_and_reports_counts(self, mock_count, mock_update):
        result = update_nuclei_templates()

        assert result["status"] == "completed"
        assert result["success"] is True
        assert result["templates_before"] == 5
        assert result["templates_after"] == 9
        mock_update.assert_called_once_with(timeout=120)

    @patch(
        "tools.update_nuclei_templates.update_nuclei_templates",
        return_value=False,
    )
    @patch(
        "tools.update_nuclei_templates.get_template_count",
        return_value=5,
    )
    def test_reports_failed_update(self, mock_count, mock_update):
        result = update_nuclei_templates(timeout=60)

        assert result["status"] == "completed"
        assert result["success"] is False
        assert result["templates_before"] == 5
        assert result["templates_after"] == 5
        mock_update.assert_called_once_with(timeout=60)

    @patch(
        "tools.update_nuclei_templates.get_template_count",
        side_effect=Exception("import error"),
    )
    def test_handles_import_failure(self, _mock_count):
        result = update_nuclei_templates()

        assert result["status"] == "error"
        assert "import error" in result["error"]


# ---------------------------------------------------------------------------
# cleanup_dlq
# ---------------------------------------------------------------------------


class TestCleanupDlq:
    """Tests for cleanup_dlq()."""

    @patch("dead_letter_queue.get_dlq")
    def test_purges_old_entries(self, mock_get_dlq):
        mock_dlq = MagicMock()
        mock_dlq.purge.return_value = 12
        mock_get_dlq.return_value = mock_dlq

        result = cleanup_dlq()

        assert result["status"] == "completed"
        assert result["purged"] == 12
        assert result["older_than_hours"] == 168
        mock_dlq.purge.assert_called_once_with(older_than_hours=168)

    @patch("dead_letter_queue.get_dlq")
    def test_passes_custom_retention(self, mock_get_dlq):
        mock_dlq = MagicMock()
        mock_dlq.purge.return_value = 3
        mock_get_dlq.return_value = mock_dlq

        result = cleanup_dlq(older_than_hours=24)

        assert result["purged"] == 3
        assert result["older_than_hours"] == 24
        mock_dlq.purge.assert_called_once_with(older_than_hours=24)

    @patch("dead_letter_queue.get_dlq")
    def test_handles_redis_failure(self, mock_get_dlq):
        mock_get_dlq.side_effect = Exception("Redis down")

        result = cleanup_dlq()

        assert result["status"] == "error"
        assert "Redis down" in result["error"]
