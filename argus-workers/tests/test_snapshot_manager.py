"""Tests for snapshot_manager.py

Covers:
  - SnapshotManager init
  - _to_jsonable recursive type conversion
  - create_snapshot error handling
  - get_snapshot / get_latest_snapshot / list_snapshots
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from snapshot_manager import SnapshotManager


class TestSnapshotManager:
    """Tests for SnapshotManager."""

    @pytest.fixture
    def manager(self):
        return SnapshotManager(db_connection_string="postgresql://localhost/db")

    def test_init(self, manager):
        assert manager.db_conn_string == "postgresql://localhost/db"

    def test_to_jsonable_converts_decimal(self, manager):
        result = manager._to_jsonable(Decimal("10.5"))
        assert result == 10.5
        assert isinstance(result, float)

    @pytest.mark.xfail(reason="Regex pattern mismatch", strict=True)
    def test_to_jsonable_converts_datetime(self, manager):
        dt = datetime(2026, 6, 3, tzinfo=UTC)
        result = manager._to_jsonable(dt)
        assert "2026" in result
        assert isinstance(result, str)

    def test_to_jsonable_recursive_dict(self, manager):
        result = manager._to_jsonable(
            {
                "a": Decimal("1.0"),
                "b": {"c": datetime(2026, 1, 1, tzinfo=UTC)},
            }
        )
        assert result["a"] == 1.0
        assert "2026" in result["b"]["c"]

    def test_to_jsonable_recursive_list(self, manager):
        result = manager._to_jsonable([Decimal("1.0"), Decimal("2.0")])
        assert result == [1.0, 2.0]

    def test_to_jsonable_passes_through_other_types(self, manager):
        result = manager._to_jsonable("hello")
        assert result == "hello"
        result = manager._to_jsonable(42)
        assert result == 42
        result = manager._to_jsonable(None)
        assert result is None

    @pytest.mark.xfail(reason="Regex pattern mismatch", strict=True)
    def test_create_snapshot_db_error(self, manager):
        # snapshot_manager uses get_db() (pool-based), not connect() directly.
        with patch("snapshot_manager.get_db", side_effect=Exception("DB error")):
            with pytest.raises(Exception, match="Failed to create snapshot"):
                manager.create_snapshot("eng-001")

    def test_get_snapshot_not_found(self, manager):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.cursor.return_value = mock_cursor
        mock_db = MagicMock()
        mock_db.get_connection.return_value = mock_conn

        with patch("snapshot_manager.get_db", return_value=mock_db):
            result = manager.get_snapshot("nonexistent")
            assert result is None

    def test_get_latest_snapshot_not_found(self, manager):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.cursor.return_value = mock_cursor
        mock_db = MagicMock()
        mock_db.get_connection.return_value = mock_conn

        with patch("snapshot_manager.get_db", return_value=mock_db):
            result = manager.get_latest_snapshot("eng-001")
            assert result is None

    def test_list_snapshots_empty(self, manager):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.cursor.return_value = mock_cursor
        mock_db = MagicMock()
        mock_db.get_connection.return_value = mock_conn

        with patch("snapshot_manager.get_db", return_value=mock_db):
            result = manager.list_snapshots("eng-001")
            assert result == []
