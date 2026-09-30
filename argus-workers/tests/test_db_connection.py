"""Tests for database/connection.py

Covers:
  - ConnectionManager singleton pattern
  - _get_connection_string with/without SSL params
  - PgBouncer mode detection
  - get_connection / release_connection lifecycle
  - connection context manager
  - cursor context manager
  - Metrics tracking
  - Error handling
  - connect helper function
  - db_connection / db_cursor convenience managers
"""

from __future__ import annotations

import logging
import os
from unittest.mock import MagicMock, patch

import pytest

from database.connection import (
    ConnectionManager,
    DatabaseConnectionError,
    LocalModeError,
    connect,
    get_db,
    local_mode_active,
    log_db_skip,
)


class TestConnectionManagerSingleton:
    """Tests for ConnectionManager singleton pattern."""

    def test_singleton_returns_same_instance(self):
        cm1 = ConnectionManager()
        cm2 = ConnectionManager()
        assert cm1 is cm2

    def test_singleton_initializes_once(self):
        # Reset for test
        ConnectionManager._instance = None
        ConnectionManager._instance_lock = MagicMock()
        cm1 = ConnectionManager()
        cm2 = ConnectionManager()
        assert cm1 is cm2

    def test_get_db_returns_same(self):
        db1 = get_db()
        db2 = get_db()
        assert db1 is db2


class TestLocalMode:
    """A local (SQLite-backed) run must not reach for PostgreSQL.

    Regression: ``argus assess --local`` pops DATABASE_URL, but a task module
    loads .env and brings it back, so the run wrote to Postgres anyway — with
    failures that named foreign keys, a missing column and ``uuid "local"``
    instead of saying there is no Postgres engagement in local mode.
    """

    def test_active_for_truthy_values(self):
        with patch.dict(os.environ, {"ARGUS_LOCAL_MODE": "1"}, clear=False):
            assert local_mode_active() is True
        with patch.dict(os.environ, {"ARGUS_LOCAL_MODE": "TRUE"}, clear=False):
            assert local_mode_active() is True

    def test_inactive_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            assert local_mode_active() is False

    def test_connection_string_refuses_postgres(self):
        cm = ConnectionManager()
        with patch.dict(
            os.environ,
            {
                "ARGUS_LOCAL_MODE": "1",
                "DATABASE_URL": "postgresql://user:pass@localhost/db",
            },
            clear=True,
        ):
            with pytest.raises(LocalModeError, match="ARGUS_LOCAL_MODE"):
                cm._get_connection_string()

    def test_error_stays_catchable_as_a_connection_error(self):
        """Components that already degrade on connect failures keep degrading."""
        assert issubclass(LocalModeError, DatabaseConnectionError)


class TestLogDbSkip:
    """The level a refused Postgres step deserves."""

    def test_local_mode_skip_is_informational(self, caplog):
        log = logging.getLogger("test.db_skip.local")
        with caplog.at_level(logging.INFO, logger="test.db_skip.local"):
            log_db_skip(log, "Failed to save remediation", LocalModeError())

        assert [r.levelno for r in caplog.records] == [logging.INFO]
        assert "local runs keep their state in SQLite" in caplog.text

    def test_any_other_failure_still_warns(self, caplog):
        log = logging.getLogger("test.db_skip.other")
        with caplog.at_level(logging.INFO, logger="test.db_skip.other"):
            log_db_skip(log, "Failed to save remediation", RuntimeError("boom"))

        assert [r.levelno for r in caplog.records] == [logging.WARNING]
        assert "Failed to save remediation: boom" in caplog.text


class TestConnectionString:
    """Tests for _get_connection_string."""

    def test_raises_when_no_env_var(self):
        cm = ConnectionManager()
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(DatabaseConnectionError, match="DATABASE_URL"):
                cm._get_connection_string()

    def test_uses_env_var(self):
        cm = ConnectionManager()
        with patch.dict(
            os.environ,
            {"DATABASE_URL": "postgresql://user:pass@localhost/db"},
            clear=False,
        ):
            result = cm._get_connection_string()
            assert "postgresql://user:pass@localhost/db" in result

    def test_adds_sslmode_when_missing(self):
        cm = ConnectionManager()
        with patch.dict(
            os.environ, {"DATABASE_URL": "postgresql://user@localhost/db"}, clear=False
        ):
            result = cm._get_connection_string()
            assert "sslmode=" in result

    def test_pgbouncer_transaction_mode(self):
        cm = ConnectionManager()
        cm._pgbouncer_mode = "transaction"
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql://user@localhost/pgbouncer",
                "USE_PGBOUNCER": "true",
            },
            clear=False,
        ):
            result = cm._get_connection_string()
            assert "statement_timeout" in result


class TestGetConnection:
    """Tests for get_connection and release_connection."""

    @pytest.fixture
    def cm(self):
        ConnectionManager._instance = None
        cm = ConnectionManager()
        yield cm

    def test_get_connection_pool_error(self, cm):
        with (
            patch.object(
                cm, "_ensure_pool", side_effect=DatabaseConnectionError("No pool")
            ),
        ):
            with pytest.raises(DatabaseConnectionError):
                cm.get_connection(timeout=1)


class TestConnectionContextManager:
    """Tests for the connection and cursor context managers."""

    def test_connection_context_commit_on_success(self):
        cm = ConnectionManager()
        mock_conn = MagicMock()
        with patch.object(cm, "get_connection", return_value=mock_conn):
            with cm.connection(commit=True) as conn:
                assert conn is mock_conn
        mock_conn.commit.assert_called_once()

    def test_connection_context_rollback_on_error(self):
        cm = ConnectionManager()
        mock_conn = MagicMock()
        with patch.object(cm, "get_connection", return_value=mock_conn):
            with pytest.raises(ValueError):
                with cm.connection(commit=True) as _:
                    raise ValueError("test error")
        mock_conn.rollback.assert_called_once()

    def test_cursor_context(self):
        cm = ConnectionManager()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        with patch.object(cm, "get_connection", return_value=mock_conn):
            with cm.cursor(commit=True) as cursor:
                assert cursor is mock_cursor

    def test_tenant_context_failure_logs_warning(self, caplog):
        """Tenant context failures should log at WARNING level."""
        import logging

        cm = ConnectionManager()
        cm._pgbouncer_mode = "session"
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        def execute_side_effect(sql, *_args):
            if "set_tenant_context" in sql:
                raise Exception("function set_tenant_context() does not exist")

        # Simulate the database function failing without depending on the
        # number of cursor health/configuration checks performed first.
        mock_cursor.execute.side_effect = execute_side_effect

        caplog.set_level(logging.WARNING)
        with patch.object(cm, "get_connection", return_value=mock_conn):
            with patch.object(cm, "release_connection"):
                # Production code re-raises after logging the warning so callers
                # know tenant isolation was not established (H-v3-12).
                with pytest.raises(Exception, match="set_tenant_context"):
                    with cm.connection(org_id="test-org-123"):
                        pass

        # Check that at least one WARNING record about tenant context was logged
        tenant_warnings = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "tenant context" in r.getMessage()
        ]
        assert len(tenant_warnings) > 0, (
            f"Expected a WARNING about tenant context failure, got: {[r.getMessage() for r in caplog.records]}"
        )
        assert "test-org-123" in tenant_warnings[0].getMessage()


class TestPoolMetrics:
    """Tests for pool metrics tracking."""

    def test_get_pool_metrics_returns_dict(self):
        cm = ConnectionManager()
        metrics = cm.get_pool_metrics()
        assert isinstance(metrics, dict)
        assert "active_connections" in metrics
        assert "idle_connections" in metrics
        assert "total_queries" in metrics
        assert "slow_queries" in metrics
        assert "total_wait_time_ms" in metrics


class TestConnectHelper:
    """Tests for the connect helper function."""

    def test_connect_raises_without_url(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(DatabaseConnectionError, match="DATABASE_URL"):
                connect()

    def test_connect_uses_env_var(self):
        # connect() without an explicit connection_string now returns a pool
        # connection via get_db().get_connection() (deprecation of one-off
        # psycopg2 connections).
        with patch.dict(
            os.environ, {"DATABASE_URL": "postgresql://user@localhost/db"}, clear=False
        ):
            with patch("database.connection.get_db") as mock_get_db:
                mock_conn = mock_get_db.return_value.get_connection.return_value
                conn = connect()
                assert conn is mock_conn

    def test_connect_with_string_arg(self):
        with patch("database.connection.psycopg2.connect") as mock_connect:
            conn = connect("postgresql://custom@localhost/db")
            mock_connect.assert_called_once_with("postgresql://custom@localhost/db")
            assert conn is mock_connect.return_value


class TestClose:
    """Tests for close method."""

    def test_close_closes_pool(self):
        cm = ConnectionManager()
        mock_pool = MagicMock()
        cm._pool = mock_pool
        cm.close()
        mock_pool.closeall.assert_called_once()
        assert cm._pool is None

    def test_close_with_no_pool(self):
        cm = ConnectionManager()
        cm._pool = None
        cm.close()  # Should not raise
