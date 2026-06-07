"""Tests for report_generation_service.py

Covers:
  - __init__ param storage
  - generate() without LLM client returns empty dict
  - generate() with LLM client generates report and SBOM
  - generate() handles exceptions gracefully
  - _generate_sbom() without DATABASE_URL raises OSError
  - _generate_sbom() loads findings and generates SBOM
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestReportGenerationServiceInit:
    """Tests for __init__ parameter storage."""

    def test_stores_params(self):
        from orchestrator_pkg.reporting.report_generation_service import (
            ReportGenerationService,
        )

        llm_client = MagicMock()
        svc = ReportGenerationService(
            engagement_id="eng-001",
            llm_client=llm_client,
            llm_model="gpt-4",
        )
        assert svc.engagement_id == "eng-001"
        assert svc.llm_client == llm_client
        assert svc.llm_model == "gpt-4"


class TestReportGenerationServiceGenerate:
    """Tests for the generate() public method."""

    @pytest.fixture
    def job(self):
        return {
            "scored_findings": [{"type": "XSS", "severity": "HIGH"}],
            "synthesis": {"summary": "test"},
            "target": "https://example.com",
            "type": "web_scan",
            "repo_url": "https://github.com/example/repo",
        }

    def test_no_llm_client_returns_empty_dict(self, job):
        from orchestrator_pkg.reporting.report_generation_service import (
            ReportGenerationService,
        )

        svc = ReportGenerationService(
            engagement_id="eng-001",
            llm_client=None,
            llm_model="gpt-4",
        )
        result = svc.generate(job)
        assert result == {}

    def test_llm_client_not_available_returns_empty(self, job):
        from orchestrator_pkg.reporting.report_generation_service import (
            ReportGenerationService,
        )

        llm_client = MagicMock()
        llm_client.is_available.return_value = False
        svc = ReportGenerationService(
            engagement_id="eng-001",
            llm_client=llm_client,
            llm_model="gpt-4",
        )
        result = svc.generate(job)
        assert result == {}

    @patch("streaming.emit_thinking")
    @patch("tasks.utils.load_recon_context")
    @patch("llm_service.LLMService")
    @patch("llm_report_generator.LLMReportGenerator")
    @patch("database.repositories.report_repository.ReportRepository")
    def test_generate_with_llm_client(
        self, mock_repo_cls, mock_generator_cls,
        mock_llm_svc_cls, mock_load_recon, mock_emit, job,
    ):
        from orchestrator_pkg.reporting.report_generation_service import (
            ReportGenerationService,
        )

        llm_client = MagicMock()
        llm_client.is_available.return_value = True

        generator_instance = MagicMock()
        generator_instance.generate_report.return_value = {"report": "content"}
        mock_generator_cls.return_value = generator_instance

        repo_instance = MagicMock()
        mock_repo_cls.return_value = repo_instance

        mock_load_recon.return_value = {"domains": ["example.com"]}

        svc = ReportGenerationService(
            engagement_id="eng-001",
            llm_client=llm_client,
            llm_model="gpt-4",
        )

        with patch.object(svc, "_generate_sbom", return_value={"sbom": "data"}):
            result = svc.generate(job)

        assert result == {"report": "content"}
        repo_instance.upsert_report.assert_called_once_with(
            engagement_id="eng-001",
            report_data={"report": "content"},
            model_used="gpt-4",
            sbom_json={"sbom": "data"},
        )

    @patch("streaming.emit_thinking")
    @patch("tasks.utils.load_recon_context")
    @patch("llm_service.LLMService")
    @patch("llm_report_generator.LLMReportGenerator")
    @patch("database.repositories.report_repository.ReportRepository")
    def test_generate_handles_exception(
        self, mock_repo_cls, mock_generator_cls,
        mock_llm_svc_cls, mock_load_recon, mock_emit, job,
    ):
        from orchestrator_pkg.reporting.report_generation_service import (
            ReportGenerationService,
        )

        llm_client = MagicMock()
        llm_client.is_available.return_value = True

        generator_instance = MagicMock()
        generator_instance.generate_report.side_effect = RuntimeError("LLM failed")
        mock_generator_cls.return_value = generator_instance

        svc = ReportGenerationService(
            engagement_id="eng-001",
            llm_client=llm_client,
            llm_model="gpt-4",
        )

        result = svc.generate(job)

        assert result == {}


class TestReportGenerationServiceGenerateSbom:
    """Tests for _generate_sbom."""

    @pytest.fixture
    def job(self):
        return {
            "target": "https://example.com",
            "repo_url": "https://github.com/example/repo",
        }

    @patch.dict(os.environ, {}, clear=True)
    def test_without_database_url_raises_oserror(self, job):
        from orchestrator_pkg.reporting.report_generation_service import (
            ReportGenerationService,
        )

        svc = ReportGenerationService(
            engagement_id="eng-001",
            llm_client=None,
            llm_model="gpt-4",
        )

        with pytest.raises(OSError, match="DATABASE_URL not set"):
            svc._generate_sbom(job)

    @patch.dict(os.environ, {"DATABASE_URL": "postgres://localhost/db"}, clear=True)
    @patch("database.repositories.finding_repository.FindingRepository")
    @patch("tools.sbom_generator.generate_sbom_from_findings")
    def test_loads_findings_and_generates_sbom(
        self, mock_sbom_gen, mock_finding_repo_cls, job,
    ):
        from orchestrator_pkg.reporting.report_generation_service import (
            ReportGenerationService,
        )

        repo_instance = MagicMock()
        findings = [{"type": "XSS", "severity": "HIGH"}]
        repo_instance.get_findings_by_engagement.return_value = (findings, 1)
        mock_finding_repo_cls.return_value = repo_instance
        mock_sbom_gen.return_value = {"sbom": "data"}

        svc = ReportGenerationService(
            engagement_id="eng-001",
            llm_client=None,
            llm_model="gpt-4",
        )

        result = svc._generate_sbom(job)

        assert result == {"sbom": "data"}
        mock_finding_repo_cls.assert_called_once_with("postgres://localhost/db")
        repo_instance.get_findings_by_engagement.assert_called_once_with(
            "eng-001", limit=10000,
        )
        mock_sbom_gen.assert_called_once_with(
            engagement_id="eng-001",
            findings=findings,
            target_url="https://example.com",
            repo_url="https://github.com/example/repo",
        )
