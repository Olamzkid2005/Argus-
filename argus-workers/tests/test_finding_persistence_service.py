"""Tests for finding_persistence_service.py

Covers:
  - __init__ param storage and default callables
  - save() short-circuits
  - save() full pipeline (normalise → preprocess → split → save)
  - _normalise_inputs() coercion logic
  - _preprocess() enrichment logic
  - _split_secret() tool-based split
  - _update_compliance_posture() scoring delegation
  - _batch_save_non_secret() batch write + emission
  - _upsert_secrets() individual upsert + emission
  - save_poc / save_remediation / _update_finding_jsonb
  - _fire_webhooks severity filtering
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestFindingPersistenceServiceInit:
    """Tests for __init__ parameter storage."""

    def test_stores_params(self):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        repo = MagicMock()
        svc = FindingPersistenceService(
            engagement_id="eng-123",
            finding_repo=repo,
            bug_bounty_mode=True,
        )
        assert svc.engagement_id == "eng-123"
        assert svc.finding_repo == repo
        assert svc.bug_bounty_mode is True

    def test_default_classify_finding_type_fn(self):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        svc = FindingPersistenceService(engagement_id="e1", finding_repo=None)
        result = svc._classify_finding_type("SOME_TYPE")
        assert result == {"owasp": "N/A", "cwe": "N/A"}

    def test_default_get_org_id_fn(self):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        svc = FindingPersistenceService(engagement_id="e1", finding_repo=None)
        assert svc._get_org_id() is None

    def test_custom_callables(self):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        classify_fn = MagicMock(return_value={"owasp": "A1", "cwe": "CWE-1"})
        org_fn = MagicMock(return_value="org-42")
        svc = FindingPersistenceService(
            engagement_id="e1",
            finding_repo=None,
            classify_finding_type_fn=classify_fn,
            get_org_id_fn=org_fn,
        )
        assert svc._classify_finding_type("TEST") == {"owasp": "A1", "cwe": "CWE-1"}
        assert svc._get_org_id() == "org-42"


class TestFindingPersistenceServiceSave:
    """Tests for the save() public method."""

    @pytest.fixture
    def svc(self):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        repo = MagicMock()
        return FindingPersistenceService(engagement_id="eng-001", finding_repo=repo)

    def test_no_repo_returns_len(self):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        svc = FindingPersistenceService(engagement_id="e1", finding_repo=None)
        result = svc.save([{"a": 1}, {"b": 2}])
        assert result == 2

    def test_empty_findings_returns_zero(self, svc):
        result = svc.save([])
        assert result == 0

    @patch("streaming.StreamingFindingEmitter")
    @patch("database.services.embedding_service.EmbeddingService")
    def test_save_full_pipeline(
        self, mock_embed, mock_emitter_cls, svc,
    ):
        emitter_instance = MagicMock()
        mock_emitter_cls.return_value = emitter_instance

        def _batch_side_effect(eng_id, f_list):
            for f in f_list:
                f["_saved_id"] = "saved-" + f.get("type", "x")
            return (1, 0)

        svc.finding_repo.batch_create_or_update_findings.side_effect = _batch_side_effect

        findings = [
            {"tool": "nuclei", "type": "XSS", "severity": "CRITICAL",
             "cvss_score": 7.5, "owasp_category": "A7", "cwe_id": "CWE-79",
             "endpoint": "/search", "evidence": {}, "confidence": 0.9,
             "source_tool": "nuclei"},
        ]

        result = svc.save(findings)

        assert result == 0
        svc.finding_repo.batch_create_or_update_findings.assert_called_once()
        emitter_instance.emit_finding.assert_called()

    @patch("streaming.StreamingFindingEmitter")
    @patch("database.services.embedding_service.EmbeddingService")
    def test_save_with_secret_findings(self, mock_embed, mock_emitter_cls, svc):
        emitter_instance = MagicMock()
        mock_emitter_cls.return_value = emitter_instance
        svc.finding_repo.upsert_secret_finding.return_value = "saved-id-1"

        findings = [
            {"type": "COMMITTED_SECRET_API_KEY", "severity": "CRITICAL",
             "cvss_score": 9.0, "endpoint": "/repo", "evidence": {},
             "confidence": 0.99, "source_tool": "gitleaks"},
        ]

        result = svc.save(findings)

        assert result == 0
        svc.finding_repo.upsert_secret_finding.assert_called_once()


class TestNormaliseInputs:
    """Tests for _normalise_inputs static method."""

    def test_dict_stays_dict(self):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        result = FindingPersistenceService._normalise_inputs([{"a": 1}])
        assert result == [{"a": 1}]

    def test_object_with_tool_output_skipped(self):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        class ToolResult:
            tool = "nuclei"
            output = "some output"

        result = FindingPersistenceService._normalise_inputs([ToolResult()])
        assert result == []

    def test_object_with_findings_flattened(self):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        class FindingsContainer:
            findings = [{"a": 1}, {"b": 2}]

        result = FindingPersistenceService._normalise_inputs([FindingsContainer()])
        assert result == [{"a": 1}, {"b": 2}]

    def test_vars_fallback(self):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        class SimpleObj:
            def __init__(self):
                self.x = 10
                self.y = 20

        result = FindingPersistenceService._normalise_inputs([SimpleObj()])
        assert result == [{"x": 10, "y": 20}]

    def test_type_error_skipped(self):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        # vars() raises TypeError for objects without __dict__
        result = FindingPersistenceService._normalise_inputs([42])
        assert result == []


class TestPreprocess:
    """Tests for _preprocess enrichment logic."""

    def test_bug_bounty_mode_sets_source(self):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        svc = FindingPersistenceService(
            engagement_id="e1", finding_repo=None, bug_bounty_mode=True,
        )
        findings = [{"type": "XSS"}]
        result = svc._preprocess(findings)
        assert result[0]["bugbounty_source"] is True
        assert result[0]["source"] == "bugbounty"

    @patch("cvss_calculator.estimate_cvss", return_value=8.5)
    def test_cvss_estimation_when_missing(self, mock_estimate):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        svc = FindingPersistenceService(engagement_id="e1", finding_repo=None)
        findings = [{"type": "XSS", "severity": "HIGH", "evidence_strength": "strong"}]
        result = svc._preprocess(findings)
        assert result[0]["cvss_score"] == 8.5
        mock_estimate.assert_called_once_with(
            finding_type="XSS", severity="HIGH", evidence_strength="strong",
        )

    def test_owasp_cwe_classification(self):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        classify = MagicMock(return_value={"owasp": "A7", "cwe": "CWE-79"})
        svc = FindingPersistenceService(
            engagement_id="e1", finding_repo=None,
            classify_finding_type_fn=classify,
        )
        findings = [{"type": "XSS", "cvss_score": 5.0}]
        result = svc._preprocess(findings)
        assert result[0]["owasp_category"] == "A7"
        assert result[0]["cwe_id"] == "CWE-79"

    def test_source_tool_fallback(self):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        svc = FindingPersistenceService(engagement_id="e1", finding_repo=None)
        findings = [{"type": "XSS", "cvss_score": 5.0, "owasp_category": "A7",
                      "cwe_id": "CWE-79"}]
        result = svc._preprocess(findings)
        assert result[0]["source_tool"] == "unknown"

    def test_tool_fallback_to_source_tool(self):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        svc = FindingPersistenceService(engagement_id="e1", finding_repo=None)
        findings = [{"type": "XSS", "cvss_score": 5.0, "tool": "nuclei",
                      "owasp_category": "A7", "cwe_id": "CWE-79"}]
        result = svc._preprocess(findings)
        assert result[0]["source_tool"] == "nuclei"

    def test_skips_cvss_when_present(self):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        svc = FindingPersistenceService(engagement_id="e1", finding_repo=None)
        findings = [{"type": "XSS", "cvss_score": 9.0, "owasp_category": "A7",
                      "cwe_id": "CWE-79"}]
        result = svc._preprocess(findings)
        assert result[0]["cvss_score"] == 9.0

    def test_skips_owasp_cwe_when_present(self):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        svc = FindingPersistenceService(engagement_id="e1", finding_repo=None)
        findings = [{"type": "XSS", "cvss_score": 5.0,
                      "owasp_category": "A1", "cwe_id": "CWE-1"}]
        result = svc._preprocess(findings)
        assert result[0]["owasp_category"] == "A1"
        assert result[0]["cwe_id"] == "CWE-1"


class TestSplitSecret:
    """Tests for _split_secret."""

    def test_non_secret_tools(self):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        svc = FindingPersistenceService(engagement_id="e1", finding_repo=None)
        findings = [
            {"source_tool": "nuclei", "type": "XSS"},
            {"source_tool": "zap", "type": "SQLI"},
        ]
        non_secret, secret = svc._split_secret(findings)
        assert len(non_secret) == 2
        assert len(secret) == 0

    def test_secret_tools(self):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        svc = FindingPersistenceService(engagement_id="e1", finding_repo=None)
        findings = [
            {"source_tool": "gitleaks", "type": "HARDCODED_SECRET"},
            {"source_tool": "trufflehog", "type": "AWS_KEY"},
            {"source_tool": "secret-scan", "type": "GITHUB_TOKEN"},
        ]
        non_secret, secret = svc._split_secret(findings)
        assert len(non_secret) == 0
        assert len(secret) == 3

    def test_committed_secret_prefix(self):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        svc = FindingPersistenceService(engagement_id="e1", finding_repo=None)
        findings = [
            {"source_tool": "nuclei", "type": "COMMITTED_SECRET_API_KEY"},
            {"source_tool": "nuclei", "type": "COMMITTED_SECRET_TOKEN"},
        ]
        non_secret, secret = svc._split_secret(findings)
        assert len(non_secret) == 0
        assert len(secret) == 2


class TestUpdateCompliancePosture:
    """Tests for _update_compliance_posture."""

    @patch("compliance_posture_scorer.CompliancePostureScorer")
    def test_calls_scorer(self, mock_scorer_cls):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        repo = MagicMock()
        class FakeFinding:
            def to_dict(self):
                return {"type": "XSS", "severity": "HIGH", "endpoint": "/api"}
        repo.get_findings_by_engagement.return_value = ([FakeFinding()], 1)
        svc = FindingPersistenceService(
            engagement_id="eng-001", finding_repo=repo,
        )

        svc._update_compliance_posture()

        mock_scorer_cls.assert_called_once_with("eng-001")
        mock_scorer_cls.return_value.compute_and_save.assert_called_once()

    @patch("compliance_posture_scorer.CompliancePostureScorer")
    def test_handles_exception_gracefully(self, mock_scorer_cls):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        repo = MagicMock()
        repo.get_findings_by_engagement.side_effect = Exception("DB error")
        svc = FindingPersistenceService(
            engagement_id="eng-001", finding_repo=repo,
        )

        svc._update_compliance_posture()  # should not raise


class TestBatchSaveNonSecret:
    """Tests for _batch_save_non_secret."""

    @patch("streaming.StreamingFindingEmitter")
    def test_batch_save_success(self, mock_emitter_cls):
        import database.repositories.finding_repository as fr_mod
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        with patch.object(fr_mod, "FindingCapExceededError", RuntimeError):
            repo = MagicMock()
            repo.batch_create_or_update_findings.return_value = (1, 0)
            svc = FindingPersistenceService(
                engagement_id="eng-001", finding_repo=repo,
            )
            emitter = MagicMock()
            findings = [{"_saved_id": "fid-1", "type": "XSS", "severity": "HIGH"}]
            result = svc._batch_save_non_secret(findings, emitter)
            assert result == 0
            emitter.emit_finding.assert_called_once_with(findings[0])

    @patch("streaming.StreamingFindingEmitter")
    def test_batch_save_cap_exceeded(self, mock_emitter_cls):
        import database.repositories.finding_repository as fr_mod
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        FakeCapError = type("FindingCapExceededError", (Exception,), {})
        with patch.object(fr_mod, "FindingCapExceededError", FakeCapError):
            repo = MagicMock()
            repo.batch_create_or_update_findings.side_effect = FakeCapError()
            svc = FindingPersistenceService(
                engagement_id="eng-001", finding_repo=repo,
            )
            result = svc._batch_save_non_secret(
                [{"type": "XSS"}], MagicMock(),
            )
            assert result == 1

    @patch("streaming.StreamingFindingEmitter")
    def test_empty_non_secret_returns_zero(self, mock_emitter_cls):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        svc = FindingPersistenceService(
            engagement_id="eng-001", finding_repo=MagicMock(),
        )
        result = svc._batch_save_non_secret([], MagicMock())
        assert result == 0


class TestUpsertSecrets:
    """Tests for _upsert_secrets."""

    @patch("streaming.StreamingFindingEmitter")
    def test_upsert_success(self, mock_emitter_cls):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        repo = MagicMock()
        repo.upsert_secret_finding.return_value = "saved-id-1"
        svc = FindingPersistenceService(
            engagement_id="eng-001", finding_repo=repo,
        )
        emitter = MagicMock()
        findings = [{"type": "COMMITTED_SECRET", "severity": "CRITICAL",
                      "endpoint": "/", "evidence": {}, "confidence": 0.9,
                      "source_tool": "gitleaks", "cvss_score": 9.0}]
        result = svc._upsert_secrets(findings, emitter)
        assert result == 0
        repo.upsert_secret_finding.assert_called_once()
        emitter.emit_finding.assert_called_once()

    @patch("streaming.StreamingFindingEmitter")
    def test_upsert_error_handled(self, mock_emitter_cls):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        repo = MagicMock()
        repo.upsert_secret_finding.side_effect = ValueError("bad data")
        svc = FindingPersistenceService(
            engagement_id="eng-001", finding_repo=repo,
        )
        findings = [{"type": "SECRET", "endpoint": "/"}]
        result = svc._upsert_secrets(findings, MagicMock())
        assert result == 1


class TestSavePocAndRemediation:
    """Tests for save_poc and save_remediation."""

    @patch("psycopg2.sql.SQL")
    @patch("psycopg2.sql.Identifier")
    @patch("database.connection.db_cursor")
    def test_save_poc(self, mock_cursor, mock_ident, mock_sql):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        cursor_instance = MagicMock()
        cursor_instance.rowcount = 1
        mock_cursor.return_value.__enter__.return_value = cursor_instance

        svc = FindingPersistenceService(engagement_id="e1", finding_repo=None)
        result = svc.save_poc("finding-1", {"proof": "data"})
        assert result is True

    @patch("psycopg2.sql.SQL")
    @patch("psycopg2.sql.Identifier")
    @patch("database.connection.db_cursor")
    def test_save_remediation(self, mock_cursor, mock_ident, mock_sql):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        cursor_instance = MagicMock()
        cursor_instance.rowcount = 1
        mock_cursor.return_value.__enter__.return_value = cursor_instance

        svc = FindingPersistenceService(engagement_id="e1", finding_repo=None)
        result = svc.save_remediation("finding-1", {"fix": "data"})
        assert result is True

    @patch("psycopg2.sql.SQL")
    @patch("psycopg2.sql.Identifier")
    @patch("database.connection.db_cursor")
    def test_update_finding_jsonb_exception(self, mock_cursor, mock_ident, mock_sql):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        mock_cursor.return_value.__enter__.side_effect = Exception("DB error")
        svc = FindingPersistenceService(engagement_id="e1", finding_repo=None)
        result = svc.save_poc("finding-1", {"data": "x"})
        assert result is False


class TestFireWebhooks:
    """Tests for _fire_webhooks."""

    @patch("post_finding_hooks.fire_finding_webhooks")
    def test_fires_for_critical(self, mock_fire):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        svc = FindingPersistenceService(engagement_id="eng-001", finding_repo=None)
        findings = [
            {"_saved_id": "f-1", "severity": "CRITICAL", "type": "SQLI",
             "endpoint": "/api", "source_tool": "nuclei", "confidence": 0.9},
            {"_saved_id": "f-2", "severity": "HIGH", "type": "XSS",
             "endpoint": "/search", "source_tool": "zap", "confidence": 0.8},
        ]
        svc._fire_webhooks(findings)
        assert mock_fire.call_count == 2

    @patch("post_finding_hooks.fire_finding_webhooks")
    def test_skips_low_medium(self, mock_fire):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        svc = FindingPersistenceService(engagement_id="eng-001", finding_repo=None)
        findings = [
            {"_saved_id": "f-1", "severity": "LOW", "type": "INFO"},
            {"_saved_id": "f-2", "severity": "MEDIUM", "type": "INFO"},
        ]
        svc._fire_webhooks(findings)
        mock_fire.assert_not_called()

    @patch("post_finding_hooks.fire_finding_webhooks")
    def test_skips_without_saved_id(self, mock_fire):
        from orchestrator_pkg.persistence.finding_persistence_service import (
            FindingPersistenceService,
        )

        svc = FindingPersistenceService(engagement_id="eng-001", finding_repo=None)
        findings = [
            {"severity": "CRITICAL", "type": "SQLI"},
        ]
        svc._fire_webhooks(findings)
        mock_fire.assert_not_called()
