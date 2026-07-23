"""
Tests for CLI --compliance flag integration in argus report command.

Verifies:
- Argument parser correctly accepts --compliance with 6 standard choices
- cmd_report() dispatches to generate_compliance_report() with correct standard
- HTML output is saved via save_report()
- Error handling for invalid standards, missing modules, and failed generation
- Edge cases: empty findings, unusual compliance standards
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from cli import build_parser, cmd_report


# ── Argument parsing tests ─────────────────────────────────────


class TestReportArgumentParser:
    """Tests for --compliance argument parsing."""

    def test_compliance_choices_present(self):
        """--compliance flag accepts all 6 valid standards."""
        parser = build_parser()
        report_parser = _find_subparser(parser, "report")
        action = _find_action(report_parser, "--compliance")
        assert action is not None, "--compliance flag not found"
        assert action.choices is not None
        assert set(action.choices) == {
            "owasp_top10", "pci_dss", "soc2",
            "nist_csf", "hipaa", "iso_27001",
        }

    def test_compliance_default_none(self):
        """--compliance defaults to None when not specified."""
        args = build_parser().parse_args(["report", "eng-001"])
        assert getattr(args, "compliance", None) is None

    def test_parse_valid_standard(self):
        """Valid compliance standard is accepted."""
        args = build_parser().parse_args(
            ["report", "eng-001", "--compliance", "owasp_top10"]
        )
        assert args.compliance == "owasp_top10"

    def test_parse_all_standards(self):
        """All 6 compliance standards parse correctly."""
        for std in ("owasp_top10", "pci_dss", "soc2", "nist_csf", "hipaa", "iso_27001"):
            args = build_parser().parse_args(
                ["report", "eng-001", "--compliance", std]
            )
            assert args.compliance == std, f"Failed for {std}"

    def test_invalid_standard_raises(self):
        """Invalid compliance standard raises SystemExit."""
        with pytest.raises(SystemExit):
            build_parser().parse_args(
                ["report", "eng-001", "--compliance", "invalid_std"]
            )

    def test_compliance_with_output(self):
        """--compliance works with --output flag."""
        args = build_parser().parse_args([
            "report", "eng-001", "--compliance", "pci_dss", "--output", "report.html"
        ])
        assert args.compliance == "pci_dss"
        assert args.output == "report.html"

    def test_compliance_with_open(self):
        """--compliance works with --open flag."""
        args = build_parser().parse_args([
            "report", "eng-001", "--compliance", "soc2", "--open"
        ])
        assert args.compliance == "soc2"
        assert args.open is True


# ── cmd_report compliance branch tests ─────────────────────────


class FakeExportResult:
    """Minimal stand-in for ExportResult to avoid importing exporter."""

    def __init__(self, path: str, size_bytes: int):
        self.path = path
        self.fmt = "html"
        self.size_bytes = size_bytes
        self.opened = False


class TestCmdReportCompliance:
    """Tests for cmd_report() compliance branch."""

    @pytest.fixture
    def mock_report_args(self):
        """Build a mock argparse.Namespace for compliance report mode."""
        args = MagicMock()
        args.compliance = "owasp_top10"
        args.engagement_id = "eng-001"
        args.output = None
        args.format = "json"
        args.open = False
        args.local = False
        args.db = ":memory:"
        args.coverage = False
        return args

    @patch("database.sqlite_backend.SQLiteFindingRepo")
    @patch("compliance_reporting.generate_compliance_report")
    @patch("reporting.exporter.save_report")
    def test_dispatches_correct_standard(
        self, mock_save, mock_generate, mock_finding_repo, mock_report_args
    ):
        """Compliance standard is passed through to generate_compliance_report()."""
        mock_finding_repo.return_value.get_findings_by_engagement.return_value = ([], 0)
        mock_finding_repo.return_value.get_summary_by_engagement.return_value = {}

        mock_generate.return_value = {
            "html": "<html>test</html>",
            "report": {"summary": {"total_findings": 0}},
        }
        mock_save.return_value = FakeExportResult("/tmp/report.html", 100)

        result = cmd_report(mock_report_args)

        assert result == 0
        mock_generate.assert_called_once_with(
            standard="owasp_top10",
            engagement_id="eng-001",
            findings=[],
        )

    @patch("database.sqlite_backend.SQLiteFindingRepo")
    @patch("compliance_reporting.generate_compliance_report")
    @patch("reporting.exporter.save_report")
    def test_all_standards_dispatched(
        self, mock_save, mock_generate, mock_finding_repo
    ):
        """All 6 compliance standards dispatch correctly."""
        mock_finding_repo.return_value.get_findings_by_engagement.return_value = ([], 0)
        mock_finding_repo.return_value.get_summary_by_engagement.return_value = {}
        mock_generate.return_value = {
            "html": "<html>test</html>",
            "report": {"summary": {}},
        }
        mock_save.return_value = FakeExportResult("/tmp/r.html", 100)

        for std in ("owasp_top10", "pci_dss", "soc2", "nist_csf", "hipaa", "iso_27001"):
            args = MagicMock()
            args.compliance = std
            args.engagement_id = "eng-001"
            args.output = None
            args.format = "json"
            args.open = False
            args.local = False
            args.db = ":memory:"
            args.coverage = False

            result = cmd_report(args)
            assert result == 0, f"Failed for standard: {std}"

        assert mock_generate.call_count == 6

    @patch("database.sqlite_backend.SQLiteFindingRepo")
    @patch("compliance_reporting.generate_compliance_report")
    @patch("reporting.exporter.save_report")
    def test_passes_findings_to_generator(
        self, mock_save, mock_generate, mock_finding_repo, mock_report_args
    ):
        """Findings from the database are passed to generate_compliance_report()."""
        sample_findings = [
            {"id": "f1", "type": "SQL_INJECTION", "severity": "CRITICAL"},
            {"id": "f2", "type": "XSS", "severity": "HIGH"},
        ]
        mock_finding_repo.return_value.get_findings_by_engagement.return_value = (
            sample_findings, 2
        )
        mock_finding_repo.return_value.get_summary_by_engagement.return_value = {
            "target_url": "https://example.com"
        }

        mock_generate.return_value = {
            "html": "<html>test</html>",
            "report": {"summary": {"total_findings": 2}},
        }
        mock_save.return_value = FakeExportResult("/tmp/r.html", 100)

        cmd_report(mock_report_args)

        mock_generate.assert_called_once_with(
            standard="owasp_top10",
            engagement_id="eng-001",
            findings=sample_findings,
        )

    @patch("database.sqlite_backend.SQLiteFindingRepo")
    @patch("compliance_reporting.generate_compliance_report")
    @patch("reporting.exporter.save_report")
    def test_saves_html_via_exporter(
        self, mock_save, mock_generate, mock_finding_repo, mock_report_args
    ):
        """HTML output is saved via save_report()."""
        mock_finding_repo.return_value.get_findings_by_engagement.return_value = ([], 0)
        mock_finding_repo.return_value.get_summary_by_engagement.return_value = {}

        expected_html = "<!DOCTYPE html><html>Compliance Report</html>"
        mock_generate.return_value = {
            "html": expected_html,
            "report": {"summary": {"total_findings": 0}},
        }
        mock_save.return_value = FakeExportResult("/tmp/owasp.html", 120)

        cmd_report(mock_report_args)

        mock_save.assert_called_once()
        call_args = mock_save.call_args[0]
        assert call_args[0] == expected_html

    @patch("database.sqlite_backend.SQLiteFindingRepo")
    @patch("compliance_reporting.generate_compliance_report")
    @patch("reporting.exporter.save_report")
    def test_prints_json_summary_when_no_output(
        self, mock_save, mock_generate, mock_finding_repo, mock_report_args, capsys
    ):
        """JSON summary printed to stdout when no --output is specified."""
        mock_finding_repo.return_value.get_findings_by_engagement.return_value = ([], 0)
        mock_finding_repo.return_value.get_summary_by_engagement.return_value = {}

        report_data = {
            "summary": {"total_findings": 3, "critical_count": 1},
            "findings": [],
        }
        mock_generate.return_value = {
            "html": "<html>test</html>",
            "report": report_data,
        }
        mock_save.return_value = FakeExportResult("/tmp/r.html", 100)

        cmd_report(mock_report_args)

        captured = capsys.readouterr()
        assert "total_findings" in captured.out
        assert "3" in captured.out

    @patch("database.sqlite_backend.SQLiteFindingRepo")
    @patch("compliance_reporting.generate_compliance_report")
    @patch("reporting.exporter.save_report")
    def test_suppresses_json_when_output_specified(
        self, mock_save, mock_generate, mock_finding_repo, capsys
    ):
        """JSON summary suppressed from stdout when --output is specified."""
        mock_finding_repo.return_value.get_findings_by_engagement.return_value = ([], 0)
        mock_finding_repo.return_value.get_summary_by_engagement.return_value = {}

        mock_generate.return_value = {
            "html": "<html>test</html>",
            "report": {"summary": {"total_findings": 0}},
        }
        mock_save.return_value = FakeExportResult("/tmp/report.html", 100)

        args = MagicMock()
        args.compliance = "pci_dss"
        args.engagement_id = "eng-001"
        args.output = "/tmp/report.html"
        args.format = "json"
        args.open = False
        args.local = False
        args.db = ":memory:"
        args.coverage = False

        cmd_report(args)

        captured = capsys.readouterr()
        assert captured.out == "", (
            "Expected no stdout when --output is specified"
        )

    @patch("database.sqlite_backend.SQLiteFindingRepo")
    @patch("compliance_reporting.generate_compliance_report")
    @patch("reporting.exporter.save_report")
    def test_logs_save_result(
        self, mock_save, mock_generate, mock_finding_repo, mock_report_args, caplog
    ):
        """Save result is logged with path and size."""
        mock_finding_repo.return_value.get_findings_by_engagement.return_value = ([], 0)
        mock_finding_repo.return_value.get_summary_by_engagement.return_value = {}

        mock_generate.return_value = {
            "html": "<html>test</html>",
            "report": {"summary": {}},
        }
        mock_save.return_value = FakeExportResult("/tmp/owasp_report.html", 5957)

        import logging
        caplog.set_level(logging.INFO)

        cmd_report(mock_report_args)

        assert any(
            "OWASP_TOP10" in msg and "5957" in msg
            for msg in caplog.messages
        ), "Log should contain standard name and file size"

    @patch("database.sqlite_backend.SQLiteFindingRepo")
    @patch("compliance_reporting.generate_compliance_report")
    @patch("reporting.exporter.save_report")
    def test_passes_open_to_save(
        self, mock_save, mock_generate, mock_finding_repo
    ):
        """--open flag is passed through to save_report()."""
        mock_finding_repo.return_value.get_findings_by_engagement.return_value = ([], 0)
        mock_finding_repo.return_value.get_summary_by_engagement.return_value = {}

        mock_generate.return_value = {
            "html": "<html>test</html>",
            "report": {"summary": {}},
        }
        mock_save.return_value = FakeExportResult("/tmp/r.html", 100)

        args = MagicMock()
        args.compliance = "owasp_top10"
        args.engagement_id = "eng-001"
        args.output = None
        args.format = "json"
        args.open = True
        args.local = False
        args.db = ":memory:"
        args.coverage = False

        cmd_report(args)

        _, kwargs = mock_save.call_args
        assert kwargs.get("open_browser") is True

    # ── Error handling tests ────────────────────────────────

    @patch("database.sqlite_backend.SQLiteFindingRepo")
    def test_import_error_handled_gracefully(self, mock_finding_repo, mock_report_args):
        """Missing compliance module returns exit code 1."""
        mock_finding_repo.return_value.get_findings_by_engagement.return_value = ([], 0)
        mock_finding_repo.return_value.get_summary_by_engagement.return_value = {}

        original_import = __builtins__["__import__"]

        def mock_import(name, *args, **kwargs):
            if name == "compliance_reporting":
                raise ImportError("No module named 'compliance_reporting'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = cmd_report(mock_report_args)
            assert result == 1

    @patch("database.sqlite_backend.SQLiteFindingRepo")
    @patch("compliance_reporting.generate_compliance_report")
    def test_generation_error_handled_gracefully(
        self, mock_generate, mock_finding_repo, mock_report_args
    ):
        """Compliance report generation failure returns exit code 1."""
        mock_finding_repo.return_value.get_findings_by_engagement.return_value = ([], 0)
        mock_finding_repo.return_value.get_summary_by_engagement.return_value = {}

        mock_generate.side_effect = ValueError("Unknown compliance standard")

        result = cmd_report(mock_report_args)
        assert result == 1

    @patch("database.sqlite_backend.SQLiteFindingRepo")
    @patch("compliance_reporting.generate_compliance_report")
    @patch("reporting.exporter.save_report")
    def test_save_error_handled_gracefully(
        self, mock_save, mock_generate, mock_finding_repo, mock_report_args
    ):
        """save_report failure propagates as exception."""
        mock_finding_repo.return_value.get_findings_by_engagement.return_value = ([], 0)
        mock_finding_repo.return_value.get_summary_by_engagement.return_value = {}

        mock_generate.return_value = {
            "html": "<html>test</html>",
            "report": {"summary": {}},
        }
        mock_save.side_effect = OSError("Permission denied")

        result = cmd_report(mock_report_args)
        assert result == 1


# ── End-to-end integration test (real modules, temp DB) ─────────


class TestComplianceIntegration:
    """End-to-end test with real SQLite backend and compliance module."""

    def test_real_compliance_report(self):
        """Generate a real compliance report with in-memory SQLite.

        This test exercises the actual compliance_reporting module
        without mocking, proving the data flow works end-to-end.
        """
        # Set up real SQLite database with sample findings
        from database.sqlite_backend import SQLiteEngagementRepo, SQLiteFindingRepo

        repo = SQLiteFindingRepo(":memory:")
        eng_repo = SQLiteEngagementRepo(":memory:")

        engagement = eng_repo.create({
            "target_url": "https://example.com",
            "org_id": "local",
            "status": "completed",
            "scan_type": "url",
        })
        eng_id = engagement["id"]

        # Create sample findings
        finding_types = [
            ("SQL_INJECTION", "CRITICAL"),
            ("XSS", "HIGH"),
            ("AUTH_FAILURE", "CRITICAL"),
            ("WEAK_TLS", "MEDIUM"),
            ("CSRF", "LOW"),
        ]
        for ftype, sev in finding_types:
            repo.create_finding(
                engagement_id=eng_id,
                finding_type=ftype,
                severity=sev,
                endpoint=f"https://example.com/{ftype.lower()}",
                evidence={},
                confidence=0.8,
                source_tool="test",
            )

        # Generate compliance report using real module
        from compliance_reporting import generate_compliance_report

        findings, total = repo.get_findings_by_engagement(eng_id, limit=100)

        result = generate_compliance_report(
            standard="owasp_top10",
            engagement_id=eng_id,
            findings=findings,
        )

        # Verify output
        html = result["html"]
        report_data = result["report"]

        assert "<!DOCTYPE html>" in html
        assert len(html) > 500
        assert report_data["summary"]["total_findings"] == 5
        assert "A03:2021 - Injection" in str(report_data)

    def test_real_compliance_report_pci(self):
        """Generate a real PCI DSS compliance report."""
        from database.sqlite_backend import SQLiteFindingRepo
        from compliance_reporting import generate_compliance_report

        repo = SQLiteFindingRepo(":memory:")
        for ftype, sev in [
            ("SQL_INJECTION", "CRITICAL"),
            ("XSS", "HIGH"),
            ("WEAK_TLS", "MEDIUM"),
        ]:
            repo.create_finding(
                engagement_id="eng-pci-test",
                finding_type=ftype,
                severity=sev,
                endpoint="/api",
                evidence={},
                confidence=0.8,
                source_tool="test",
            )

        findings, _ = repo.get_findings_by_engagement("eng-pci-test", limit=100)
        result = generate_compliance_report("pci_dss", "eng-pci-test", findings)

        html = result["html"]
        report_data = result["report"]

        assert "<!DOCTYPE html>" in html
        assert len(html) > 500
        assert report_data["summary"]["total_findings"] == 3
        # PCI DSS should have 14 requirements
        assert report_data["summary"]["total_requirements"] == 14


# ── Helper functions ──────────────────────────────────────────


def _find_subparser(parser, name: str):
    """Find a subparser by command name."""
    for action in parser._subparsers._group_actions:
        if hasattr(action, "choices"):
            for choice_name, choice_parser in action.choices.items():
                if choice_name == name:
                    return choice_parser
    return None


def _find_action(parser, option_string: str):
    """Find an action by option string."""
    for action in parser._actions:
        if option_string in action.option_strings:
            return action
    return None
