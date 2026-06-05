"""Tests for target_profile_service.py

Covers:
  - __init__ param storage
  - update() without target_domain returns early
  - update() loads findings, recon context, tool accuracy, upserts profile
  - update() handles exceptions gracefully
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestTargetProfileServiceInit:
    """Tests for __init__ parameter storage."""

    def test_stores_params(self):
        from orchestrator_pkg.reporting.target_profile_service import (
            TargetProfileService,
        )

        repo = MagicMock()
        org_fn = MagicMock(return_value="org-42")
        svc = TargetProfileService(
            engagement_id="eng-001",
            finding_repo=repo,
            get_org_id_fn=org_fn,
        )
        assert svc.engagement_id == "eng-001"
        assert svc.finding_repo == repo
        assert svc._get_org_id() == "org-42"


class TestTargetProfileServiceUpdate:
    """Tests for the update() public method."""

    @pytest.fixture
    def svc(self):
        from orchestrator_pkg.reporting.target_profile_service import (
            TargetProfileService,
        )

        repo = MagicMock()
        org_fn = MagicMock(return_value="org-42")
        return TargetProfileService(
            engagement_id="eng-001",
            finding_repo=repo,
            get_org_id_fn=org_fn,
        )

    def test_no_target_domain_returns_early(self, svc):
        result = svc.update({"target": ""})
        assert result is None

    def test_no_org_id_returns_early(self, svc):
        from orchestrator_pkg.reporting.target_profile_service import (
            TargetProfileService,
        )

        repo = MagicMock()
        org_fn = MagicMock(return_value=None)
        svc2 = TargetProfileService(
            engagement_id="eng-001",
            finding_repo=repo,
            get_org_id_fn=org_fn,
        )
        result = svc2.update({"target": "https://example.com"})
        assert result is None

    @patch("database.repositories.target_profile_repository.TargetProfileRepository")
    @patch("database.repositories.tool_accuracy_repository.ToolAccuracyRepository")
    @patch("tasks.utils.load_recon_context")
    def test_update_loads_data_and_upserts(
        self, mock_load_recon, mock_acc_repo_cls,
        mock_profile_repo_cls, svc,
    ):
        mock_recon = MagicMock()
        mock_recon.to_dict.return_value = {"domains": ["example.com"]}
        mock_load_recon.return_value = mock_recon

        acc_repo_instance = MagicMock()
        acc_repo_instance.load_fp_rates.return_value = {"nuclei": 0.05}
        mock_acc_repo_cls.return_value = acc_repo_instance

        profile_repo_instance = MagicMock()
        mock_profile_repo_cls.return_value = profile_repo_instance

        findings = [
            MagicMock(to_dict=MagicMock(return_value={"type": "XSS"})),
            {"type": "SQLI"},
        ]
        svc.finding_repo.get_findings_by_engagement.return_value = (findings, 2)

        svc.update({
            "target": "https://example.com",
        })

        mock_profile_repo_cls.return_value.upsert_from_engagement.assert_called_once_with(
            org_id="org-42",
            target_url="https://example.com",
            engagement_id="eng-001",
            recon_context={"domains": ["example.com"]},
            findings=[{"type": "XSS"}, {"type": "SQLI"}],
            tool_accuracy_fp_rates={"nuclei": 0.05},
        )

    @patch("database.repositories.target_profile_repository.TargetProfileRepository")
    @patch("database.repositories.tool_accuracy_repository.ToolAccuracyRepository")
    @patch("tasks.utils.load_recon_context")
    def test_no_finding_repo_uses_empty(
        self, mock_load_recon, mock_acc_repo_cls,
        mock_profile_repo_cls,
    ):
        from orchestrator_pkg.reporting.target_profile_service import (
            TargetProfileService,
        )

        org_fn = MagicMock(return_value="org-42")
        svc = TargetProfileService(
            engagement_id="eng-001",
            finding_repo=None,
            get_org_id_fn=org_fn,
        )

        mock_recon = MagicMock()
        mock_recon.to_dict.return_value = {}
        mock_load_recon.return_value = mock_recon

        svc.update({"target": "https://example.com"})

        mock_profile_repo_cls.return_value.upsert_from_engagement.assert_called_once()

    @patch("database.repositories.target_profile_repository.TargetProfileRepository")
    @patch("database.repositories.tool_accuracy_repository.ToolAccuracyRepository")
    @patch("tasks.utils.load_recon_context")
    def test_handles_exception_gracefully(
        self, mock_load_recon, mock_acc_repo_cls,
        mock_profile_repo_cls, svc,
    ):
        svc.finding_repo.get_findings_by_engagement.side_effect = Exception("DB error")

        svc.update({"target": "https://example.com"})
        # Should not raise
