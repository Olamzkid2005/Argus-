"""Tests for snapshot_service.py"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from orchestrator_pkg.analysis.snapshot_service import SnapshotService


class TestSnapshotService:
    def test_init_stores_params_correctly(self):
        mock_repo = MagicMock()
        get_org_id = MagicMock()
        load_priority = MagicMock()
        state = MagicMock()
        svc = SnapshotService(
            db_conn="db://conn",
            engagement_id="eng-123",
            finding_repo=mock_repo,
            get_org_id_fn=get_org_id,
            load_priority_vuln_classes_fn=load_priority,
            state=state,
        )
        assert svc.db_conn == "db://conn"
        assert svc.engagement_id == "eng-123"
        assert svc.finding_repo is mock_repo
        assert svc._get_org_id is get_org_id
        assert svc._load_priority_vuln_classes is load_priority
        assert svc._state is state

    @patch("snapshot_manager.SnapshotManager")
    @patch("loop_budget_manager.LoopBudgetManager")
    def test_load_and_build_without_finding_repo_still_creates_snapshot_and_budget(
        self, MockBudgetMgr, MockSnapshotMgr
    ):
        mock_snapshot_mgr = MagicMock()
        mock_snapshot_mgr.create_snapshot.return_value = {"engagement_id": "eng-123"}
        MockSnapshotMgr.return_value = mock_snapshot_mgr

        mock_budget_mgr = MagicMock()
        mock_budget_mgr.to_dict.return_value = {"cycles": 5}
        MockBudgetMgr.return_value = mock_budget_mgr

        get_org_id = MagicMock()
        get_org_id.return_value = "org-1"
        load_priority = MagicMock()
        load_priority.return_value = []

        svc = SnapshotService(
            db_conn="db://conn",
            engagement_id="eng-123",
            finding_repo=None,
            get_org_id_fn=get_org_id,
            load_priority_vuln_classes_fn=load_priority,
        )
        job = {"budget": {"max_cycles": 10}}
        snapshot, budget_mgr, findings, org_id = svc.load_and_build(job)

        MockSnapshotMgr.assert_called_once_with("db://conn")
        mock_snapshot_mgr.create_snapshot.assert_called_once_with("eng-123")
        MockBudgetMgr.assert_called_once_with("eng-123", {"max_cycles": 10})
        assert findings == []
        assert snapshot["findings"] == []
        assert snapshot["loop_budget"] == {"cycles": 5}
        assert org_id == "org-1"

    @patch("snapshot_manager.SnapshotManager")
    @patch("loop_budget_manager.LoopBudgetManager")
    def test_load_and_build_with_finding_repo_loads_findings(
        self, MockBudgetMgr, MockSnapshotMgr
    ):
        mock_snapshot_mgr = MagicMock()
        mock_snapshot_mgr.create_snapshot.return_value = {}
        MockSnapshotMgr.return_value = mock_snapshot_mgr
        MockBudgetMgr.return_value = MagicMock()

        mock_repo = MagicMock()
        mock_finding = MagicMock()
        mock_finding.to_dict.return_value = {"id": "f1", "type": "xss"}
        mock_repo.get_findings_by_engagement.return_value = ([mock_finding], 1)

        get_org_id = MagicMock()
        get_org_id.return_value = None
        load_priority = MagicMock()
        load_priority.return_value = []

        svc = SnapshotService(
            db_conn="db://conn",
            engagement_id="eng-123",
            finding_repo=mock_repo,
            get_org_id_fn=get_org_id,
            load_priority_vuln_classes_fn=load_priority,
        )
        snapshot, budget_mgr, findings, org_id = svc.load_and_build({})

        mock_repo.get_findings_by_engagement.assert_called_once_with(
            "eng-123", limit=100000,
        )
        assert findings == [{"id": "f1", "type": "xss"}]
        assert snapshot["findings"] == [{"id": "f1", "type": "xss"}]

    @patch("snapshot_manager.SnapshotManager")
    @patch("loop_budget_manager.LoopBudgetManager")
    def test_load_and_build_without_db_conn_raises_oserror(
        self, MockBudgetMgr, MockSnapshotMgr
    ):
        svc = SnapshotService(
            db_conn="",
            engagement_id="eng-123",
            finding_repo=None,
            get_org_id_fn=MagicMock(),
            load_priority_vuln_classes_fn=MagicMock(),
        )
        with pytest.raises(OSError, match="DATABASE_URL is not set"):
            svc.load_and_build({})

    @patch("snapshot_manager.SnapshotManager")
    @patch("loop_budget_manager.LoopBudgetManager")
    @patch("database.connection.db_cursor")
    def test_load_and_build_loads_loop_budget_from_db(
        self, mock_db_cursor, MockBudgetMgr, MockSnapshotMgr
    ):
        mock_snapshot_mgr = MagicMock()
        mock_snapshot_mgr.create_snapshot.return_value = {}
        MockSnapshotMgr.return_value = mock_snapshot_mgr

        mock_budget_mgr = MagicMock()
        mock_budget_mgr.to_dict.return_value = {}
        MockBudgetMgr.return_value = mock_budget_mgr

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (3, 1, 5)
        mock_db_cursor.return_value.__enter__.return_value = mock_cursor

        get_org_id = MagicMock()
        get_org_id.return_value = None
        load_priority = MagicMock()
        load_priority.return_value = []

        svc = SnapshotService(
            db_conn="db://conn",
            engagement_id="eng-123",
            finding_repo=None,
            get_org_id_fn=get_org_id,
            load_priority_vuln_classes_fn=load_priority,
        )
        svc.load_and_build({})

        mock_budget_mgr.load_from_db.assert_called_once_with(
            {
                "current_cycles": 3,
                "current_depth": 1,
                "current_llm_reviews": 5,
            },
        )

    @patch("snapshot_manager.SnapshotManager")
    @patch("loop_budget_manager.LoopBudgetManager")
    def test_load_and_build_sets_org_id_priority_vuln_classes_and_engagement_state(
        self, MockBudgetMgr, MockSnapshotMgr
    ):
        mock_snapshot_mgr = MagicMock()
        mock_snapshot_mgr.create_snapshot.return_value = {}
        MockSnapshotMgr.return_value = mock_snapshot_mgr
        MockBudgetMgr.return_value = MagicMock()

        get_org_id = MagicMock()
        get_org_id.return_value = "org-42"
        load_priority = MagicMock()
        load_priority.return_value = ["SQLI", "XSS"]
        state = MagicMock()

        svc = SnapshotService(
            db_conn="db://conn",
            engagement_id="eng-123",
            finding_repo=None,
            get_org_id_fn=get_org_id,
            load_priority_vuln_classes_fn=load_priority,
            state=state,
        )
        snapshot, _, _, org_id = svc.load_and_build({})

        assert org_id == "org-42"
        assert snapshot["org_id"] == "org-42"
        assert snapshot["priority_vuln_classes"] == ["SQLI", "XSS"]
        assert snapshot["_engagement_state"] is state
