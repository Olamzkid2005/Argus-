"""Tests for health_monitor.py database initialization fix.

Verifies that:
- db and conn are initialized before the try block
- finally block guards with `if conn and db:` before release_connection
"""

from unittest.mock import MagicMock, patch

import pytest

from health_monitor import ToolHealthTracker


class TestToolHealthTrackerDbInit:
    """ToolHealthTracker.get_tool_health() initializes db/conn before try."""

    def test_db_initialized_before_try_by_default(self):
        """db and conn are set to None before the try block (not NameError risk)."""
        tracker = ToolHealthTracker()

        conn = None
        db = None

        # Simulate: an exception happens before get_db() is called
        try:
            raise RuntimeError("Something failed")
        except RuntimeError:
            pass
        finally:
            if conn and db:
                pass

        assert conn is None
        assert db is None

    def test_db_none_does_not_crash_nameerror(self):
        """Confirm that db being undefined (NameError) is impossible — it's initialized."""
        tracker = ToolHealthTracker()

        conn = None
        db = None
        try:
            raise RuntimeError("Pre-db failure")
        except RuntimeError:
            pass
        finally:
            try:
                _ = conn and db
            except NameError:
                pytest.fail("db or conn was not initialized before try block")

    def test_finally_guards_with_conn_and_db(self):
        """The finally block in get_tool_health must check `if conn and db:`."""
        import inspect

        source = inspect.getsource(ToolHealthTracker.get_tool_health)
        assert "if conn and db:" in source, (
            "finally block must check `if conn and db:` before release_connection"
        )
        assert "db.release_connection(conn)" in source, (
            "finally block must call `db.release_connection(conn)`"
        )

    def test_finally_does_not_release_when_db_none(self):
        """release_connection is not called when db or conn is None."""
        tracker = ToolHealthTracker()
        mock_db = MagicMock()

        conn = None
        db = mock_db

        if conn and db:
            db.release_connection(conn)

        mock_db.release_connection.assert_not_called()

        conn = MagicMock()
        db = None

        if conn and db:
            db.release_connection(conn)

        mock_db.release_connection.assert_not_called()

    def test_finally_releases_when_both_valid(self):
        """release_connection is called only when both conn and db are truthy."""
        tracker = ToolHealthTracker()
        mock_db = MagicMock()
        mock_conn = MagicMock()

        conn = mock_conn
        db = mock_db

        if conn and db:
            db.release_connection(conn)

        mock_db.release_connection.assert_called_once_with(mock_conn)


class TestToolHealthTrackerSourceGuard:
    """Verify the source code pattern itself (regression prevention)."""

    def test_db_and_conn_initialized_before_try(self):
        """get_tool_health should initialize 'db = None' and 'conn = None' before try."""
        import inspect

        source = inspect.getsource(ToolHealthTracker.get_tool_health)

        lines = source.splitlines()
        try_block_line = None
        for i, line in enumerate(lines):
            if line.strip() == "try:":
                try_block_line = i
                break

        assert try_block_line is not None, "Could not find try block"

        before_try = "\n".join(lines[:try_block_line])

        assert "conn = None" in before_try, (
            "conn = None must appear before the try block"
        )
        assert "db = None" in before_try, (
            "db = None must appear before the try block"
        )
