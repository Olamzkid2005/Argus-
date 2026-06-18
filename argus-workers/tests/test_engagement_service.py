"""Unit tests for EngagementService.

Tests the three static methods extracted from Orchestrator:
- load_priority_vuln_classes(engagement_id)
- get_scan_state(engagement_id)
- log_timeout_event(engagement_id, elapsed_seconds)
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestEngagementService:
    """Tests for EngagementService static methods."""

    # ── DB cursor patch helper ─────────────────────────────────

    @pytest.fixture
    def mock_db_cursor(self):
        """Patch database.connection.db_cursor and return a mock cursor."""
        with patch("database.connection.db_cursor") as mock_db:
            cursor = MagicMock()
            mock_db.return_value.__enter__.return_value = cursor
            yield cursor

    # ── load_priority_vuln_classes ──────────────────────────────

    def test_load_priority_vuln_classes_returns_list(self, mock_db_cursor):
        """Happy path: DB returns a list of priority vuln classes."""
        from orchestrator_pkg.engagement.engagement_service import EngagementService

        mock_db_cursor.fetchone.return_value = (["SQL_INJECTION", "XSS", "RCE"],)

        result = EngagementService.load_priority_vuln_classes("eng-123")

        assert result == ["SQL_INJECTION", "XSS", "RCE"]
        mock_db_cursor.execute.assert_called_once_with(
            "SELECT priority_vuln_classes FROM engagements WHERE id = %s",
            ("eng-123",),
        )

    def test_load_priority_vuln_classes_empty_when_null(self, mock_db_cursor):
        """When DB returns None for priority_vuln_classes, returns []."""
        from orchestrator_pkg.engagement.engagement_service import EngagementService

        mock_db_cursor.fetchone.return_value = (None,)
        result = EngagementService.load_priority_vuln_classes("eng-456")

        assert result == []

    def test_load_priority_vuln_classes_empty_when_no_row(self, mock_db_cursor):
        """When no engagement row exists, returns []."""
        from orchestrator_pkg.engagement.engagement_service import EngagementService

        mock_db_cursor.fetchone.return_value = None
        result = EngagementService.load_priority_vuln_classes("eng-nonexistent")

        assert result == []

    def test_load_priority_vuln_classes_logs_warning_on_exception(self, caplog):
        """Exception during DB query is caught, logged, and returns []."""
        from orchestrator_pkg.engagement.engagement_service import EngagementService

        with patch("database.connection.db_cursor") as mock_db:
            mock_db.return_value.__enter__.side_effect = RuntimeError(
                "Connection refused"
            )
            result = EngagementService.load_priority_vuln_classes("eng-bad")

        assert result == []
        assert "Failed to load priority_vuln_classes for eng-bad" in caplog.text

    # ── get_scan_state ──────────────────────────────────────────

    def test_get_scan_state_returns_status(self, mock_db_cursor):
        """Happy path: DB returns a status string."""
        from orchestrator_pkg.engagement.engagement_service import EngagementService

        mock_db_cursor.fetchone.return_value = ("scanning",)
        result = EngagementService.get_scan_state("eng-123")

        assert result == "scanning"
        mock_db_cursor.execute.assert_called_once_with(
            "SELECT status FROM engagements WHERE id = %s",
            ("eng-123",),
        )

    def test_get_scan_state_defaults_to_recon_when_no_row(self, mock_db_cursor):
        """When no engagement row exists, returns 'recon'."""
        from orchestrator_pkg.engagement.engagement_service import EngagementService

        mock_db_cursor.fetchone.return_value = None
        result = EngagementService.get_scan_state("eng-new")

        assert result == "recon"

    def test_get_scan_state_logs_warning_and_returns_failed(self, caplog):
        """ValueError is caught, logged, and returns 'failed'."""
        from orchestrator_pkg.engagement.engagement_service import EngagementService

        with patch("database.connection.db_cursor") as mock_db:
            mock_db.return_value.__enter__.side_effect = KeyError("bad key")
            result = EngagementService.get_scan_state("eng-bad")

        assert result == "failed"
        assert "State check failed for engagement eng-bad" in caplog.text
        assert "defaulting to 'failed'" in caplog.text

    def test_get_scan_state_lets_unexpected_exception_propagate(self):
        """Exceptions not in (ValueError, OSError, KeyError) propagate."""
        from orchestrator_pkg.engagement.engagement_service import EngagementService

        with patch("database.connection.db_cursor") as mock_db:
            mock_db.return_value.__enter__.side_effect = TypeError("unexpected")
            with pytest.raises(TypeError, match="unexpected"):
                EngagementService.get_scan_state("eng-bad")

    # ── log_timeout_event ───────────────────────────────────────

    def test_log_timeout_event_logs_warning(self, caplog):
        """log_timeout_event logs a warning with engagement ID and elapsed time."""
        import logging

        from orchestrator_pkg.engagement.engagement_service import EngagementService

        caplog.set_level(logging.WARNING)

        EngagementService.log_timeout_event("eng-timed-out", 1234.56)

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelname == "WARNING"
        assert "eng-timed-out" in record.getMessage()
        assert "1234.56" in record.getMessage() or "1234" in record.getMessage()
        assert "7200" in record.getMessage()  # HARD_TIMEOUT_SECONDS

    def test_log_timeout_event_formats_elapsed_with_two_decimals(self, caplog):
        """Elapsed seconds should be formatted with 2 decimal places."""
        import logging

        from orchestrator_pkg.engagement.engagement_service import EngagementService

        caplog.set_level(logging.WARNING)

        EngagementService.log_timeout_event("eng-t", 12.34567)

        assert "12.34" in caplog.text or "12.35" in caplog.text  # 2dp rounding
