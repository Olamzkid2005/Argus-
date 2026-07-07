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

import os
from unittest.mock import MagicMock, patch

import pytest

from database.connection import (
    ConnectionManager,
    DatabaseConnectionError,
    connect,
    get_db,
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
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        # Simulate set_tenant_context raising an error
        mock_cursor.execute.side_effect = Exception("function set_tenant_context() does not exist")

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
        with patch.dict(
            os.environ, {"DATABASE_URL": "postgresql://user@localhost/db"}, clear=False
        ):
            with patch("database.connection.psycopg2.connect") as mock_connect:
                conn = connect()
                assert conn is mock_connect.return_value

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
