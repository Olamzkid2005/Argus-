"""
Tests for checkpoint_manager.py
"""
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from checkpoint_manager import CheckpointContext, CheckpointManager


class TestCheckpointManager:
    """Test suite for CheckpointManager"""

    @pytest.fixture
    def mock_db_conn(self):
        """Create a mock DB via get_db() — CheckpointManager uses the pool, not psycopg2.connect directly"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        mock_db = MagicMock()
        mock_db.get_connection.return_value = mock_conn

        with patch("checkpoint_manager.get_db", return_value=mock_db):
            yield mock_db, mock_conn, mock_cursor

    @pytest.fixture
    def manager(self):
        return CheckpointManager("postgresql://test:test@localhost:5432/test_db")

    def test_save_checkpoint(self, manager, mock_db_conn):
        """Test saving a checkpoint"""
        mock_db, mock_conn, mock_cursor = mock_db_conn

        with patch("checkpoint_manager.uuid.uuid4") as mock_uuid:
            mock_uuid.return_value = "test-uuid-123"
            checkpoint_id = manager.save_checkpoint("ENG-001", "scan", {"findings": []})

        assert checkpoint_id == "test-uuid-123"
        mock_cursor.execute.assert_called_once()
        mock_conn.commit.assert_called_once()
        mock_cursor.close.assert_called_once()
        mock_db.release_connection.assert_called_once_with(mock_conn)

    def test_save_checkpoint_rollback_on_error(self, manager, mock_db_conn):
        """Test rollback when save fails"""
        mock_db, mock_conn, mock_cursor = mock_db_conn
        mock_cursor.execute.side_effect = Exception("DB error")

        with pytest.raises(Exception, match="Failed to save checkpoint"):
            manager.save_checkpoint("ENG-001", "scan", {"findings": []})

        mock_conn.rollback.assert_called_once()
        mock_cursor.close.assert_called_once()
        mock_db.release_connection.assert_called_once_with(mock_conn)

    def test_load_checkpoint_found(self, manager, mock_db_conn):
        """Test loading an existing checkpoint"""
        mock_db, mock_conn, mock_cursor = mock_db_conn
        mock_cursor.fetchone.return_value = {
            "id": "chk-001",
            "engagement_id": "ENG-001",
            "phase": "scan",
            "data": {"findings": ["f1"]},
            "created_at": datetime(2024, 1, 1, 12, 0, 0),
        }

        result = manager.load_checkpoint("ENG-001")

        assert result is not None
        assert result["id"] == "chk-001"
        assert result["phase"] == "scan"
        assert result["data"] == {"findings": ["f1"]}

    def test_load_checkpoint_not_found(self, manager, mock_db_conn):
        """Test loading when no checkpoint exists"""
        mock_db, mock_conn, mock_cursor = mock_db_conn
        mock_cursor.fetchone.return_value = None

        result = manager.load_checkpoint("ENG-999")

        assert result is None

    def test_has_checkpoint_true(self, manager, mock_db_conn):
        """Test has_checkpoint returns True"""
        mock_db, mock_conn, mock_cursor = mock_db_conn
        mock_cursor.fetchone.return_value = (5,)

        assert manager.has_checkpoint("ENG-001") is True

    def test_has_checkpoint_false(self, manager, mock_db_conn):
        """Test has_checkpoint returns False"""
        mock_db, mock_conn, mock_cursor = mock_db_conn
        mock_cursor.fetchone.return_value = (0,)

        assert manager.has_checkpoint("ENG-001") is False

    def test_list_checkpoints(self, manager, mock_db_conn):
        """Test listing checkpoints"""
        mock_db, mock_conn, mock_cursor = mock_db_conn
        mock_cursor.fetchall.return_value = [
            {"id": "chk-002", "engagement_id": "ENG-001", "phase": "analyze", "created_at": datetime(2024, 1, 2)},
            {"id": "chk-001", "engagement_id": "ENG-001", "phase": "scan", "created_at": datetime(2024, 1, 1)},
        ]

        results = manager.list_checkpoints("ENG-001")

        assert len(results) == 2
        assert results[0]["phase"] == "analyze"
        assert results[1]["phase"] == "scan"

    def test_delete_checkpoints(self, manager, mock_db_conn):
        """Test deleting checkpoints"""
        mock_db, mock_conn, mock_cursor = mock_db_conn

        manager.delete_checkpoints("ENG-001")

        mock_conn.commit.assert_called_once()
        mock_cursor.close.assert_called_once()
        mock_db.release_connection.assert_called_once_with(mock_conn)

    def test_delete_checkpoints_rollback_on_error(self, manager, mock_db_conn):
        """Test rollback on delete error"""
        mock_db, mock_conn, mock_cursor = mock_db_conn
        mock_cursor.execute.side_effect = Exception("DB error")

        with pytest.raises(Exception, match="Failed to delete checkpoints"):
            manager.delete_checkpoints("ENG-001")

        mock_conn.rollback.assert_called_once()

    def test_resume_from_checkpoint_found(self, manager, mock_db_conn):
        """Test resuming from existing checkpoint"""
        mock_db, mock_conn, mock_cursor = mock_db_conn
        created_at = datetime(2024, 1, 1, 12, 0, 0)
        mock_cursor.fetchone.return_value = {
            "id": "chk-001",
            "engagement_id": "ENG-001",
            "phase": "scan",
            "data": {"findings": ["f1"]},
            "created_at": created_at,
        }

        result = manager.resume_from_checkpoint("ENG-001")

        assert result is not None
        assert result["engagement_id"] == "ENG-001"
        assert result["resume_phase"] == "scan"
        assert result["partial_results"] == {"findings": ["f1"]}
        assert result["checkpoint_timestamp"] == created_at.isoformat()

    def test_resume_from_checkpoint_not_found(self, manager, mock_db_conn):
        """Test resuming when no checkpoint exists"""
        mock_db, mock_conn, mock_cursor = mock_db_conn
        mock_cursor.fetchone.return_value = None

        result = manager.resume_from_checkpoint("ENG-999")
        assert result is None

    def test_get_resume_plan_middle_phase(self, manager, mock_db_conn):
        """Test resume plan from middle phase"""
        mock_db, mock_conn, mock_cursor = mock_db_conn
        created_at = datetime(2024, 1, 1, 12, 0, 0)
        mock_cursor.fetchone.return_value = {
            "id": "chk-001",
            "engagement_id": "ENG-001",
            "phase": "scan",
            "data": {"findings": ["f1"]},
            "created_at": created_at,
        }

        plan = manager.get_resume_plan("ENG-001")

        assert plan is not None
        assert plan["engagement_id"] == "ENG-001"
        assert plan["completed_phase"] == "scan"
        assert plan["next_phase"] == "analyze"
        assert plan["remaining_phases"] == ["analyze", "report"]
        assert plan["can_resume"] is True

    def test_get_resume_plan_last_phase(self, manager, mock_db_conn):
        """Test resume plan from last phase"""
        mock_db, mock_conn, mock_cursor = mock_db_conn
        mock_cursor.fetchone.return_value = {
            "id": "chk-001",
            "engagement_id": "ENG-001",
            "phase": "report",
            "data": {},
            "created_at": datetime(2024, 1, 1, 12, 0, 0),
        }

        plan = manager.get_resume_plan("ENG-001")

        assert plan["next_phase"] is None
        assert plan["remaining_phases"] == []

    def test_get_resume_plan_unknown_phase(self, manager, mock_db_conn):
        """Test resume plan with unknown phase defaults to first"""
        mock_db, mock_conn, mock_cursor = mock_db_conn
        mock_cursor.fetchone.return_value = {
            "id": "chk-001",
            "engagement_id": "ENG-001",
            "phase": "custom_phase",
            "data": {},
            "created_at": datetime(2024, 1, 1, 12, 0, 0),
        }

        plan = manager.get_resume_plan("ENG-001")

        assert plan["next_phase"] == "scan"
        assert plan["remaining_phases"] == ["scan", "analyze", "report"]

    def test_get_resume_plan_no_checkpoint(self, manager, mock_db_conn):
        """Test resume plan when no checkpoint exists"""
        mock_db, mock_conn, mock_cursor = mock_db_conn
        mock_cursor.fetchone.return_value = None

        plan = manager.get_resume_plan("ENG-999")
        assert plan is None

    def test_cleanup_old_checkpoints(self, manager, mock_db_conn):
        """Test cleaning up old checkpoints"""
        mock_db, mock_conn, mock_cursor = mock_db_conn
        mock_cursor.rowcount = 3

        deleted = manager.cleanup_old_checkpoints(max_age_days=7)

        assert deleted == 3
        mock_cursor.execute.assert_called_once()
        args = mock_cursor.execute.call_args[0][1]
        cutoff = args[0]
        assert isinstance(cutoff, datetime)
        assert cutoff < datetime.now(UTC)
        mock_conn.commit.assert_called_once()

    def test_cleanup_old_checkpoints_rollback_on_error(self, manager, mock_db_conn):
        """Test rollback on cleanup error"""
        mock_db, mock_conn, mock_cursor = mock_db_conn
        mock_cursor.execute.side_effect = Exception("DB error")

        with pytest.raises(Exception, match="Failed to cleanup checkpoints"):
            manager.cleanup_old_checkpoints(max_age_days=7)

        mock_conn.rollback.assert_called_once()


class TestCheckpointContext:
    """Test suite for CheckpointContext"""

    @pytest.fixture
    def mock_manager(self):
        return MagicMock(spec=CheckpointManager)

    def test_context_manager_saves_on_success(self, mock_manager):
        """Test checkpoint saved when no exception"""
        with CheckpointContext(mock_manager, "ENG-001", "scan") as ctx:
            ctx.add_result("findings", ["f1", "f2"])

        mock_manager.save_checkpoint.assert_called_once_with(
            "ENG-001", "scan", {"findings": ["f1", "f2"]}
        )

    def test_context_manager_does_not_save_on_exception(self, mock_manager):
        """Test checkpoint not saved when exception occurs"""
        with (
            pytest.raises(ValueError, match="test error"),
            CheckpointContext(mock_manager, "ENG-001", "scan") as ctx,
        ):
            ctx.add_result("findings", ["f1"])
            raise ValueError("test error")

        mock_manager.save_checkpoint.assert_not_called()

    def test_context_manager_add_result(self, mock_manager):
        """Test adding multiple results"""
        with CheckpointContext(mock_manager, "ENG-001", "recon") as ctx:
            ctx.add_result("endpoints", ["/api", "/admin"])
            ctx.add_result("domains", ["example.com"])

        mock_manager.save_checkpoint.assert_called_once_with(
            "ENG-001", "recon", {"endpoints": ["/api", "/admin"], "domains": ["example.com"]}
        )
