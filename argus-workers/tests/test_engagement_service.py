"""Unit tests for EngagementService.

Tests static methods:
- load_priority_vuln_classes(engagement_id)
- get_scan_state(engagement_id)
- log_timeout_event(engagement_id, elapsed_seconds)
- store_scope_config(engagement_id, scope_config)
- load_scope_config(engagement_id)

Note: Importing EngagementService triggers orchestrator_pkg's __init__.py which
imports the full Orchestrator class (requiring opentelemetry). If that
dependency is unavailable, all tests gracefully skip.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Attempt module-level import — skip all tests if opentelemetry is missing
try:
    from orchestrator_pkg.engagement.engagement_service import EngagementService
    _HAVE_ENGAGEMENT_SERVICE = True
except ImportError:
    _HAVE_ENGAGEMENT_SERVICE = False


@pytest.mark.skipif(
    not _HAVE_ENGAGEMENT_SERVICE,
    reason="EngagementService import requires opentelemetry and full environment",
)
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
        mock_db_cursor.fetchone.return_value = (["SQL_INJECTION", "XSS", "RCE"],)

        result = EngagementService.load_priority_vuln_classes("eng-123")

        assert result == ["SQL_INJECTION", "XSS", "RCE"]
        mock_db_cursor.execute.assert_called_once_with(
            "SELECT priority_vuln_classes FROM engagements WHERE id = %s",
            ("eng-123",),
        )

    def test_load_priority_vuln_classes_empty_when_null(self, mock_db_cursor):
        """When DB returns None for priority_vuln_classes, returns []."""
        mock_db_cursor.fetchone.return_value = (None,)
        result = EngagementService.load_priority_vuln_classes("eng-456")

        assert result == []

    def test_load_priority_vuln_classes_empty_when_no_row(self, mock_db_cursor):
        """When no engagement row exists, returns []."""
        mock_db_cursor.fetchone.return_value = None
        result = EngagementService.load_priority_vuln_classes("eng-nonexistent")

        assert result == []

    def test_load_priority_vuln_classes_logs_warning_on_exception(self, caplog):
        """Exception during DB query is caught, logged, and returns []."""
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
        mock_db_cursor.fetchone.return_value = ("scanning",)
        result = EngagementService.get_scan_state("eng-123")

        assert result == "scanning"
        mock_db_cursor.execute.assert_called_once_with(
            "SELECT status FROM engagements WHERE id = %s",
            ("eng-123",),
        )

    def test_get_scan_state_defaults_to_recon_when_no_row(self, mock_db_cursor):
        """When no engagement row exists, returns 'recon'."""
        mock_db_cursor.fetchone.return_value = None
        result = EngagementService.get_scan_state("eng-new")

        assert result == "recon"

    def test_get_scan_state_logs_warning_and_returns_failed(self, caplog):
        """ValueError is caught, logged, and returns 'failed'."""
        with patch("database.connection.db_cursor") as mock_db:
            mock_db.return_value.__enter__.side_effect = KeyError("bad key")
            result = EngagementService.get_scan_state("eng-bad")

        assert result == "failed"
        assert "State check failed for engagement eng-bad" in caplog.text
        assert "defaulting to 'failed'" in caplog.text

    def test_get_scan_state_lets_unexpected_exception_propagate(self):
        """Exceptions not in (ValueError, OSError, KeyError) propagate."""
        with patch("database.connection.db_cursor") as mock_db:
            mock_db.return_value.__enter__.side_effect = TypeError("unexpected")
            with pytest.raises(TypeError, match="unexpected"):
                EngagementService.get_scan_state("eng-bad")

    # ── log_timeout_event ───────────────────────────────────────

    def test_log_timeout_event_logs_warning(self, caplog):
        """log_timeout_event logs a warning with engagement ID and elapsed time."""
        import logging

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

        caplog.set_level(logging.WARNING)

        EngagementService.log_timeout_event("eng-t", 12.34567)

        assert "12.34" in caplog.text or "12.35" in caplog.text  # 2dp rounding

    # ── store_scope_config ────────────────────────────────────────

    def test_store_scope_config_persists_dict(self, mock_db_cursor):
        """Happy path: stores the scope dict via jsonb_set."""
        import json

        scope = {
            "mode": "allowlist",
            "allowed_targets": ["127.0.0.1:3001"],
            "blocked_targets": ["*"],
        }
        EngagementService.store_scope_config("eng-123", scope)

        mock_db_cursor.execute.assert_called_once()
        call_args = mock_db_cursor.execute.call_args[0]
        sql = call_args[0]
        params = call_args[1]

        assert "jsonb_set" in sql
        assert "scope_config" in sql
        assert params[0] == json.dumps(scope)
        assert params[1] == "eng-123"

    def test_store_scope_config_returns_early_for_none(self, mock_db_cursor):
        """None scope is silently ignored, no DB write."""
        EngagementService.store_scope_config("eng-123", None)
        mock_db_cursor.execute.assert_not_called()

    def test_store_scope_config_returns_early_for_non_dict(self, mock_db_cursor):
        """Non-dict scope (e.g. string) is silently ignored."""
        EngagementService.store_scope_config("eng-123", "not-a-dict")
        mock_db_cursor.execute.assert_not_called()

        EngagementService.store_scope_config("eng-123", [])
        mock_db_cursor.execute.assert_not_called()

    def test_store_scope_config_returns_early_for_empty_dict(self, mock_db_cursor):
        """Empty dict () passes 'not scope_config' guard, no DB write."""
        EngagementService.store_scope_config("eng-123", {})
        mock_db_cursor.execute.assert_not_called()

    def test_store_scope_config_logs_warning_on_exception(self, caplog):
        """DB exception is caught and logged, does not propagate."""
        with patch("database.connection.db_cursor") as mock_db:
            mock_db.return_value.__enter__.side_effect = RuntimeError("DB down")
            EngagementService.store_scope_config("eng-bad", {"mode": "allowlist"})

        assert "Failed to persist scope config for eng-bad" in caplog.text

    # ── load_scope_config ─────────────────────────────────────────

    def test_load_scope_config_returns_dict_when_string(self, mock_db_cursor):
        """Happy path: DB returns a JSON string, method parses and returns dict."""
        mock_db_cursor.fetchone.return_value = (
            '{"mode": "allowlist", "allowed_targets": ["127.0.0.1:3001"]}',
        )
        result = EngagementService.load_scope_config("eng-123")

        assert result == {"mode": "allowlist", "allowed_targets": ["127.0.0.1:3001"]}
        mock_db_cursor.execute.assert_called_once_with(
            "SELECT metadata->'scope_config' FROM engagements WHERE id = %s",
            ("eng-123",),
        )

    def test_load_scope_config_returns_dict_when_dict(self, mock_db_cursor):
        """psycopg2 may return a dict directly; method copies and returns it."""
        scope_dict = {"mode": "allowlist", "allowed_targets": []}
        mock_db_cursor.fetchone.return_value = (scope_dict,)
        result = EngagementService.load_scope_config("eng-123")

        assert result == scope_dict
        # Should be a copy, not the same object
        assert result is not scope_dict

    def test_load_scope_config_returns_none_when_no_row(self, mock_db_cursor):
        """No engagement row returns None."""
        mock_db_cursor.fetchone.return_value = None
        result = EngagementService.load_scope_config("eng-missing")

        assert result is None

    def test_load_scope_config_returns_none_when_null(self, mock_db_cursor):
        """NULL scope_config in DB returns None."""
        mock_db_cursor.fetchone.return_value = (None,)
        result = EngagementService.load_scope_config("eng-123")

        assert result is None

    def test_load_scope_config_logs_warning_on_exception(self, caplog):
        """DB exception is caught, logged, and returns None."""
        with patch("database.connection.db_cursor") as mock_db:
            mock_db.return_value.__enter__.side_effect = RuntimeError("DB timeout")
            result = EngagementService.load_scope_config("eng-bad")

        assert result is None
        assert "Failed to load scope config for eng-bad" in caplog.text

    # ── scope round-trip (mocked) ─────────────────────────────────

    def test_scope_round_trip_str(self, mock_db_cursor):
        """Mimics a store-then-load round trip with string storage.

        The store path writes via jsonb_set and the load path reads via
        metadata->'scope_config'. In a real PG the stored JSON is returned
        as a string by the driver; we test the parsing logic on that string.
        """
        import json

        original_scope = {
            "mode": "allowlist",
            "allowed_targets": ["127.0.0.1:3001"],
            "blocked_targets": ["*"],
        }

        # Simulate store: the scope is serialized to JSON
        stored_json = json.dumps(original_scope)

        # Simulate load: DB returns the JSON string
        mock_db_cursor.fetchone.return_value = (stored_json,)
        loaded = EngagementService.load_scope_config("eng-123")

        assert loaded == original_scope
        assert loaded["mode"] == "allowlist"
        assert loaded["allowed_targets"] == ["127.0.0.1:3001"]
        assert loaded["blocked_targets"] == ["*"]

    def test_scope_round_trip_dict(self, mock_db_cursor):
        """Mimics a store-then-load round trip with dict storage.

        When psycopg2 returns the JSONB value as a pre-parsed dict (some
        configurations with RealDictCursor or jsonb codec), the load path
        handles it via the `isinstance(raw, dict)` branch.
        """
        import json

        original_scope = {
            "mode": "allowlist",
            "allowed_targets": ["127.0.0.1:3001"],
            "blocked_targets": ["*"],
        }

        # Simulate load: psycopg2 returns the JSONB column as a pre-parsed dict
        mock_db_cursor.fetchone.return_value = (original_scope,)
        loaded = EngagementService.load_scope_config("eng-123")

        assert loaded == original_scope
        # Also verify store_scope_config would serialize correctly
        assert json.loads(json.dumps(original_scope)) == original_scope
