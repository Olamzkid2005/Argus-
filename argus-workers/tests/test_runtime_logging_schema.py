"""Hermetic coverage for runtime logging/scheduling DDL."""

from pathlib import Path
from unittest.mock import MagicMock, patch

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "database"
    / "migrations"
    / "032_runtime_logging_tables.sql"
)
MIGRATION_SQL = MIGRATION_PATH.read_text(encoding="utf-8")


def test_tracked_migration_covers_runtime_tables():
    """The migration ledger must define every table runtime code touches."""
    for table in (
        "scheduled_engagements",
        "execution_logs",
        "execution_spans",
        "agent_decision_log",
        "agent_state_log",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table} (" in MIGRATION_SQL


def test_scheduled_engagement_schema_matches_spawn_query():
    """Spawn/select/update code must find its scheduled-engagement columns."""
    for column in (
        "org_id",
        "target_url",
        "authorized_scope",
        "scan_type",
        "aggressiveness",
        "agent_mode",
        "created_by",
        "cron_expression",
        "enabled",
        "last_engagement_id",
        "last_run_at",
        "next_run_at",
    ):
        assert column in MIGRATION_SQL


def test_execution_log_schema_matches_structured_logger():
    """Structured logging must find its execution-log columns."""
    for column in (
        "engagement_id",
        "trace_id",
        "event_type",
        "message",
        "metadata",
        "created_at",
    ):
        assert column in MIGRATION_SQL


def test_uuid_defaults_do_not_require_uuid_ossp():
    """Use built-in UUID generation for every runtime-logging table."""
    assert "gen_random_uuid()" in MIGRATION_SQL
    assert "uuid_generate_v4()" not in MIGRATION_SQL


def test_runtime_bootstrap_uses_tracked_migration():
    """Runtime bootstrapping must execute the tracked migration DDL."""
    from runtime.migration import ensure_tables

    with patch("database.connection.db_cursor") as mock_cursor:
        mock_cm = MagicMock()
        mock_cursor.return_value.__enter__.return_value = mock_cm
        assert ensure_tables() is True

    mock_cm.execute.assert_called_once_with(MIGRATION_SQL)
