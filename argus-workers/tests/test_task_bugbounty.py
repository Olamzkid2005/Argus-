"""Tests for tasks.bugbounty — Bug Bounty Report Celery Task."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from tasks.bugbounty import _fetch_engagement, _fetch_findings
from tasks.bugbounty import generate_bugbounty_report as _generate_bugbounty_report_task

# Call the original unwrapped function to avoid Celery auto-retry wrapper
generate_bugbounty_report = _generate_bugbounty_report_task._orig_run

# Helper: set a fake DATABASE_URL for tests that connect
DB_URL = "postgres://test:test@localhost:5432/testdb"


@pytest.fixture
def celery_task():
    task = MagicMock()
    task.request.retries = 0
    return task


class TestFetchFindings:
    """Tests for _fetch_findings()."""

    @patch("tasks.bugbounty.os.getenv", return_value=None)
    def test_without_database_url_raises_oserror(self, mock_getenv):
        with pytest.raises(OSError, match="DATABASE_URL not set"):
            _fetch_findings("eng-001")

    @patch.dict(os.environ, {"DATABASE_URL": DB_URL})
    @patch("psycopg2.connect")
    def test_returns_parsed_findings_with_json_evidence(self, mock_connect):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        mock_cursor.fetchall.return_value = [
            {
                "id": "f1",
                "engagement_id": "eng-001",
                "type": "SQL_INJECTION",
                "severity": "HIGH",
                "confidence": 0.9,
                "endpoint": "https://example.com",
                "source_tool": "nuclei",
                "description": "SQL injection found",
                "remediation": "Sanitize inputs",
                "evidence": '{"payload": "test", "response": "error"}',
                "repro_steps": None,
                "cvss_score": 8.5,
                "cwe_id": "CWE-89",
                "verified": True,
                "created_at": None,
                "embedding": None,
                "llm_analysis": None,
                "fp_likelihood": None,
                "evidence_strength": None,
                "tool_agreement_level": None,
                "needs_validation": False,
            }
        ]

        findings = _fetch_findings("eng-001")

        assert len(findings) == 1
        assert findings[0]["evidence"] == {"payload": "test", "response": "error"}
        mock_conn.close.assert_called_once()

    @patch.dict(os.environ, {"DATABASE_URL": DB_URL})
    @patch("psycopg2.connect")
    def test_handles_string_evidence_parsing(self, mock_connect):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        mock_cursor.fetchall.return_value = [
            {
                "id": "f2",
                "engagement_id": "eng-001",
                "type": "XSS",
                "severity": "MEDIUM",
                "confidence": 0.7,
                "endpoint": "https://example.com",
                "source_tool": "nuclei",
                "description": "XSS found",
                "remediation": "Encode output",
                "evidence": "raw text evidence",
                "repro_steps": None,
                "cvss_score": 6.0,
                "cwe_id": "CWE-79",
                "verified": True,
                "created_at": None,
                "embedding": None,
                "llm_analysis": None,
                "fp_likelihood": None,
                "evidence_strength": None,
                "tool_agreement_level": None,
                "needs_validation": False,
            }
        ]

        findings = _fetch_findings("eng-001")

        assert len(findings) == 1
        assert findings[0]["evidence"] == {"raw": "raw text evidence"}
        mock_conn.close.assert_called_once()


class TestFetchEngagement:
    """Tests for _fetch_engagement()."""

    @patch.dict(os.environ, {"DATABASE_URL": DB_URL})
    @patch("psycopg2.connect")
    def test_returns_engagement_dict(self, mock_connect):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        mock_cursor.fetchone.return_value = {
            "id": "eng-001",
            "target_url": "https://example.com",
            "status": "completed",
            "scan_type": "full",
            "created_at": None,
            "completed_at": None,
        }

        result = _fetch_engagement("eng-001")
        assert result == {
            "id": "eng-001",
            "target_url": "https://example.com",
            "status": "completed",
            "scan_type": "full",
            "created_at": None,
            "completed_at": None,
        }
        mock_conn.close.assert_called_once()

    @patch.dict(os.environ, {"DATABASE_URL": DB_URL})
    @patch("psycopg2.connect")
    def test_returns_none_when_not_found(self, mock_connect):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None

        result = _fetch_engagement("eng-999")
        assert result is None
        mock_conn.close.assert_called_once()


class TestGenerateBugBountyReport:
    """Tests for generate_bugbounty_report()."""

    @patch("tasks.bugbounty._fetch_engagement")
    @patch("tasks.bugbounty._fetch_findings")
    def test_no_findings_returns_no_findings_status(
        self, mock_fetch_findings, mock_fetch_engagement
    ):
        mock_fetch_findings.return_value = []
        mock_fetch_engagement.return_value = {"id": "eng-001", "target_url": "https://example.com"}

        result = generate_bugbounty_report(
            "eng-001", "hackerone", output_path=""
        )

        assert result["status"] == "no_findings"
        assert result["engagement_id"] == "eng-001"

    @patch("tasks.bugbounty.Path.write_text")
    @patch("tasks.bugbounty.Path.mkdir")
    @patch("tasks.bugbounty.BugBountyReportGenerator")
    @patch("tasks.bugbounty._fetch_engagement")
    @patch("tasks.bugbounty._fetch_findings")
    def test_generates_report_and_writes_to_file(
        self,
        mock_fetch_findings,
        mock_fetch_engagement,
        mock_generator_cls,
        mock_mkdir,
        mock_write_text,
    ):
        mock_fetch_findings.return_value = [{"id": "f1", "type": "SQL_INJECTION", "severity": "HIGH"}]
        mock_fetch_engagement.return_value = {"id": "eng-001", "target_url": "https://example.com"}
        mock_generator = MagicMock()
        mock_generator_cls.return_value = mock_generator
        mock_generator.generate.return_value = "# Report content"

        result = generate_bugbounty_report(
            "eng-001", "bugcrowd", output_path="/tmp/report.md"
        )

        assert result["status"] == "completed"
        assert result["output_path"] == "/tmp/report.md"
        assert result["findings_count"] == 1
        mock_write_text.assert_called_once_with("# Report content", encoding="utf-8")

    @patch("tasks.bugbounty.BugBountyReportGenerator")
    @patch("tasks.bugbounty._fetch_engagement")
    @patch("tasks.bugbounty._fetch_findings")
    def test_handles_value_error_from_generator(
        self,
        mock_fetch_findings,
        mock_fetch_engagement,
        mock_generator_cls,
    ):
        mock_fetch_findings.return_value = [{"id": "f1", "type": "SQL_INJECTION", "severity": "HIGH"}]
        mock_fetch_engagement.return_value = {"id": "eng-001", "target_url": "https://example.com"}
        mock_generator = MagicMock()
        mock_generator_cls.return_value = mock_generator
        mock_generator.generate.side_effect = ValueError("Unsupported platform")

        result = generate_bugbounty_report(
            "eng-001", "unknown", output_path="/tmp/report.md"
        )

        assert result["status"] == "failed"
        assert "Unsupported platform" in result["error"]

    @patch("tasks.bugbounty.Path.write_text")
    @patch("tasks.bugbounty.Path.mkdir")
    @patch("tasks.bugbounty.BugBountyReportGenerator")
    @patch("tasks.bugbounty._fetch_engagement")
    @patch("tasks.bugbounty._fetch_findings")
    def test_no_output_path_uses_default_reports_dir(
        self,
        mock_fetch_findings,
        mock_fetch_engagement,
        mock_generator_cls,
        mock_mkdir,
        mock_write_text,
    ):
        mock_fetch_findings.return_value = [{"id": "f1", "type": "SQL_INJECTION", "severity": "HIGH"}]
        mock_fetch_engagement.return_value = {"id": "eng-001", "target_url": "https://example.com"}
        mock_generator = MagicMock()
        mock_generator_cls.return_value = mock_generator
        mock_generator.generate.return_value = "# Report content"

        result = generate_bugbounty_report(
            "eng-001", "intigriti", output_path=""
        )

        assert result["status"] == "completed"
        assert "reports/bugbounty_intigriti_" in result["output_path"]

    @patch("tasks.bugbounty._fetch_engagement")
    @patch("tasks.bugbounty._fetch_findings")
    def test_retries_on_fetch_failure(
        self, mock_fetch_findings, mock_fetch_engagement
    ):
        mock_fetch_findings.side_effect = Exception("DB connection lost")
        # The bound task's self is the real Celery task — patch retry on it
        from tasks.bugbounty import generate_bugbounty_report as _task
        bound_self = _task._orig_run.__self__
        bound_self.request.retries = 0
        orig_retry = bound_self.retry
        bound_self.retry = MagicMock(side_effect=Exception("Retry triggered"))

        try:
            with pytest.raises(Exception, match="Retry triggered"):
                generate_bugbounty_report("eng-001", "hackerone")
        finally:
            bound_self.retry = orig_retry
