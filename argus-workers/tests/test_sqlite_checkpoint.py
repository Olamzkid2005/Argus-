"""
Tests for database/sqlite_checkpoint.py — SQLite-backed checkpoint manager.

Uses real in-memory SQLite (not mocking) for full CRUD verification.
"""

import pytest

from database.sqlite_checkpoint import SQLiteCheckpointManager


class TestSQLiteCheckpointManager:
    """Test suite for SQLiteCheckpointManager."""

    @pytest.fixture
    def mgr(self):
        m = SQLiteCheckpointManager(":memory:")
        yield m
        m.close()

    def test_save_and_load_latest(self, mgr):
        """Save a checkpoint and load it back via load_latest_checkpoint."""
        cpid = mgr.save_checkpoint(
            "eng-001", "recon",
            {"target": "https://example.com", "findings_count": 5},
        )
        assert cpid is not None
        assert isinstance(cpid, str)

        loaded = mgr.load_latest_checkpoint("eng-001")
        assert loaded is not None
        assert loaded["engagement_id"] == "eng-001"
        assert loaded["phase"] == "recon"
        assert loaded["data"]["target"] == "https://example.com"

    def test_load_empty_db(self, mgr):
        """Loading from empty DB returns None."""
        assert mgr.load_latest_checkpoint("nonexistent") is None

    def test_latest_checkpoint_multiple(self, mgr):
        """Latest checkpoint is returned when multiple exist."""
        mgr.save_checkpoint("eng-001", "recon", {"phase": "recon"})
        mgr.save_checkpoint("eng-001", "scan", {"phase": "scan"})
        mgr.save_checkpoint("eng-001", "analyze", {"phase": "analyze"})

        latest = mgr.load_latest_checkpoint("eng-001")
        assert latest["phase"] == "analyze"
        assert latest["data"]["phase"] == "analyze"

    def test_get_resume_plan_middle_phase(self, mgr):
        """Resume from middle phase returns correct remaining phases."""
        mgr.save_checkpoint("eng-001", "recon", {})
        mgr.save_checkpoint("eng-001", "scan", {})

        plan = mgr.get_resume_plan("eng-001")
        assert plan is not None
        assert plan.can_resume is True
        assert plan.next_phase == "analyze"
        assert plan.remaining_phases == ["analyze", "report"]
        assert plan.completed_phase == "scan"

    def test_get_resume_plan_complete(self, mgr):
        """Engagement with all phases completed -> cannot resume."""
        for phase in ("recon", "scan", "analyze", "report"):
            mgr.save_checkpoint("eng-001", phase, {})
        plan = mgr.get_resume_plan("eng-001")
        assert plan is not None
        assert plan.can_resume is False
        assert plan.remaining_phases == []

    def test_get_resume_plan_no_checkpoint(self, mgr):
        """No checkpoint -> None."""
        assert mgr.get_resume_plan("nonexistent") is None

    def test_get_resume_plan_recon_only(self, mgr):
        """Only recon done -> resume from scan."""
        mgr.save_checkpoint("eng-001", "recon", {})
        plan = mgr.get_resume_plan("eng-001")
        assert plan is not None
        assert plan.can_resume is True
        assert plan.next_phase == "scan"
        assert plan.remaining_phases == ["scan", "analyze", "report"]

    def test_has_checkpoint_true(self, mgr):
        """Checkpoint exists for engagement."""
        mgr.save_checkpoint("eng-001", "recon", {})
        assert mgr.has_checkpoint("eng-001") is True

    def test_has_checkpoint_false(self, mgr):
        """No checkpoint for engagement."""
        assert mgr.has_checkpoint("eng-001") is False

    def test_delete_checkpoints(self, mgr):
        """Delete all checkpoints for an engagement."""
        mgr.save_checkpoint("eng-001", "recon", {})
        mgr.save_checkpoint("eng-001", "scan", {})
        assert mgr.has_checkpoint("eng-001") is True

        mgr.delete_checkpoints("eng-001")
        assert mgr.has_checkpoint("eng-001") is False

    def test_list_checkpoints(self, mgr):
        """List all checkpoints for engagement."""
        mgr.save_checkpoint("eng-001", "recon", {"f": 1})
        mgr.save_checkpoint("eng-001", "scan", {"f": 2})
        results = mgr.list_checkpoints("eng-001")
        assert len(results) == 2
        phases = [r["phase"] for r in results]
        assert "recon" in phases
        assert "scan" in phases

    def test_list_checkpoints_empty(self, mgr):
        """Empty list when no checkpoints."""
        assert mgr.list_checkpoints("eng-001") == []

    def test_close_releases_connection(self, mgr):
        """Close does not raise."""
        mgr.close()

    def test_non_serializable_data(self, mgr):
        """Data with non-serializable types uses default=str."""
        from datetime import datetime, timezone

        data = {"timestamp": datetime.now(timezone.utc), "count": 42}
        cpid = mgr.save_checkpoint("eng-001", "recon", data)
        assert cpid is not None

        loaded = mgr.load_latest_checkpoint("eng-001")
        assert loaded["data"]["count"] == 42

    def test_multiple_engagements_independent(self, mgr):
        """Checkpoints for different engagements are independent."""
        mgr.save_checkpoint("eng-a", "recon", {"a": 1})
        mgr.save_checkpoint("eng-b", "scan", {"b": 2})

        assert mgr.has_checkpoint("eng-a") is True
        assert mgr.has_checkpoint("eng-b") is True

        plan_a = mgr.get_resume_plan("eng-a")
        assert plan_a.next_phase == "scan"

        plan_b = mgr.get_resume_plan("eng-b")
        assert plan_b.next_phase == "analyze"

        mgr.delete_checkpoints("eng-a")
        assert mgr.has_checkpoint("eng-a") is False
        assert mgr.has_checkpoint("eng-b") is True


class TestSQLiteCheckpointEdgeCases:
    """Edge case tests for SQLiteCheckpointManager."""

    @pytest.fixture
    def mgr(self):
        m = SQLiteCheckpointManager(":memory:")
        yield m
        m.close()

    def test_empty_data(self, mgr):
        """Empty dict as data is OK."""
        mgr.save_checkpoint("eng-001", "recon", {})
        loaded = mgr.load_latest_checkpoint("eng-001")
        assert loaded["data"] == {}

    def test_large_data(self, mgr):
        """Large serializable data is handled."""
        data = {"big": "x" * 10000}
        mgr.save_checkpoint("eng-001", "recon", data)
        loaded = mgr.load_latest_checkpoint("eng-001")
        assert len(loaded["data"]["big"]) == 10000

    def test_save_after_delete(self, mgr):
        """Can save new checkpoint after deleting old ones."""
        mgr.save_checkpoint("eng-001", "recon", {"v": 1})
        mgr.delete_checkpoints("eng-001")
        mgr.save_checkpoint("eng-001", "scan", {"v": 2})
        loaded = mgr.load_latest_checkpoint("eng-001")
        assert loaded["data"]["v"] == 2

    def test_phase_data_preserved(self, mgr):
        """Partial results from previous phases are preserved."""
        phase_results = [{"phase": "recon", "findings": ["ep1", "ep2"]}]
        mgr.save_checkpoint("eng-001", "recon", {
            "target": "x.com",
            "phase_results": phase_results,
        })
        plan = mgr.get_resume_plan("eng-001")
        assert len(plan.partial_results["phase_results"]) == 1
        assert plan.partial_results["target"] == "x.com"
