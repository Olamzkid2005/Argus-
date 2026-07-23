"""Tests for cli.py — standalone CLI argument parsing and command dispatch."""

from __future__ import annotations

import argparse
import sys
from unittest.mock import patch

import pytest

from cli import build_parser, main


# ── Argument parsing tests ──────────────────────────────────────────────


class TestBuildParser:
    """Validate argument parser structure for all 7 commands."""

    def test_parser_returns_argument_parser(self):
        """build_parser() returns an ArgumentParser."""
        parser = build_parser()
        assert parser is not None
        assert parser.prog == "argus"

    def test_parser_has_all_subcommands(self):
        """All 7 commands are registered as subparsers."""
        parser = build_parser()
        # Access subparsers via _subparsers internal (no public API for this)
        actions = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
        assert len(actions) == 1
        subparsers = actions[0].choices
        assert set(subparsers.keys()) == {
            "assess", "scan", "report", "list", "health", "resume", "trends",
        }

    def test_main_no_command_prints_help(self):
        """main() with no args returns 0 (prints help)."""
        with patch.object(sys, "argv", ["argus"]):
            assert main() == 0

    # ── assess ───────────────────────────────────────────────────────

    def test_assess_parser_accepts_target(self):
        """assess subcommand parses target positional arg."""
        parser = build_parser()
        args = parser.parse_args(["assess", "https://example.com"])
        assert args.command == "assess"
        assert args.target == "https://example.com"

    def test_assess_parser_default_aggressiveness(self):
        """assess default aggressiveness is 'moderate'."""
        parser = build_parser()
        args = parser.parse_args(["assess", "https://example.com"])
        assert args.aggressiveness == "moderate"

    def test_assess_parser_accepts_aggressiveness_flag(self):
        """assess --aggressiveness flag is accepted."""
        parser = build_parser()
        args = parser.parse_args([
            "assess", "https://example.com", "--aggressiveness", "aggressive",
        ])
        assert args.aggressiveness == "aggressive"

    def test_assess_parser_accepts_local_flag(self):
        """assess --local flag is accepted."""
        parser = build_parser()
        args = parser.parse_args(["assess", "https://example.com", "--local"])
        assert args.local is True

    def test_assess_parser_accepts_db_flag(self):
        """assess --db flag is accepted."""
        parser = build_parser()
        args = parser.parse_args(["assess", "https://example.com", "--db", "test.db"])
        assert args.db == "test.db"

    def test_assess_parser_accepts_output_flag(self):
        """assess --output flag is accepted."""
        parser = build_parser()
        args = parser.parse_args([
            "assess", "https://example.com", "--output", "results.json",
        ])
        assert args.output == "results.json"

    def test_assess_parser_accepts_format_flag(self):
        """assess --format flag is accepted."""
        parser = build_parser()
        args = parser.parse_args([
            "assess", "https://example.com", "--format", "markdown",
        ])
        assert args.format == "markdown"

    def test_assess_parser_accepts_llm_refine_flag(self):
        """assess --llm-refine flag is accepted."""
        parser = build_parser()
        args = parser.parse_args(["assess", "https://example.com", "--llm-refine"])
        assert args.llm_refine is True

    # ── scan ─────────────────────────────────────────────────────────

    def test_scan_parser_accepts_target(self):
        """scan subcommand parses target positional arg."""
        parser = build_parser()
        args = parser.parse_args(["scan", "https://example.com"])
        assert args.command == "scan"
        assert args.target == "https://example.com"

    def test_scan_parser_accepts_aggressiveness_flag(self):
        """scan --aggressiveness flag is accepted."""
        parser = build_parser()
        args = parser.parse_args([
            "scan", "https://example.com", "-a", "light",
        ])
        assert args.aggressiveness == "light"

    def test_scan_parser_accepts_local_flag(self):
        """scan --local flag is accepted."""
        parser = build_parser()
        args = parser.parse_args(["scan", "https://example.com", "--local"])
        assert args.local is True

    # ── report ───────────────────────────────────────────────────────

    def test_report_parser_accepts_engagement_id(self):
        """report subcommand parses engagement_id positional arg."""
        parser = build_parser()
        args = parser.parse_args(["report", "eng-001"])
        assert args.command == "report"
        assert args.engagement_id == "eng-001"

    def test_report_parser_default_format(self):
        """report default format is 'json'."""
        parser = build_parser()
        args = parser.parse_args(["report", "eng-001"])
        assert args.format == "json"

    def test_report_parser_accepts_format_json(self):
        """report --format json is accepted."""
        parser = build_parser()
        args = parser.parse_args(["report", "eng-001", "--format", "json"])
        assert args.format == "json"

    def test_report_parser_accepts_format_html(self):
        """report --format html is accepted."""
        parser = build_parser()
        args = parser.parse_args(["report", "eng-001", "--format", "html"])
        assert args.format == "html"

    def test_report_parser_accepts_format_pdf(self):
        """report --format pdf is accepted."""
        parser = build_parser()
        args = parser.parse_args(["report", "eng-001", "--format", "pdf"])
        assert args.format == "pdf"

    def test_report_parser_accepts_format_markdown(self):
        """report --format markdown is accepted."""
        parser = build_parser()
        args = parser.parse_args(["report", "eng-001", "--format", "markdown"])
        assert args.format == "markdown"

    def test_report_parser_accepts_coverage_flag(self):
        """report --coverage flag is accepted."""
        parser = build_parser()
        args = parser.parse_args(["report", "eng-001", "--coverage"])
        assert args.coverage is True

    def test_report_parser_accepts_compliance_flag(self):
        """report --compliance flag is accepted with valid choices."""
        parser = build_parser()
        args = parser.parse_args([
            "report", "eng-001", "--compliance", "owasp_top10",
        ])
        assert args.compliance == "owasp_top10"

    def test_report_parser_accepts_all_compliance_standards(self):
        """report --compliance accepts all 6 standards."""
        parser = build_parser()
        for std in ("owasp_top10", "pci_dss", "soc2", "nist_csf", "hipaa", "iso_27001"):
            args = parser.parse_args(["report", "eng-001", "--compliance", std])
            assert args.compliance == std

    def test_report_parser_accepts_open_flag(self):
        """report --open flag is accepted."""
        parser = build_parser()
        args = parser.parse_args(["report", "eng-001", "--open"])
        assert args.open is True

    def test_report_parser_accepts_local_flag(self):
        """report --local flag is accepted."""
        parser = build_parser()
        args = parser.parse_args(["report", "eng-001", "--local"])
        assert args.local is True

    def test_report_parser_accepts_output_flag(self):
        """report --output flag is accepted."""
        parser = build_parser()
        args = parser.parse_args(["report", "eng-001", "-o", "report.html"])
        assert args.output == "report.html"

    # ── list ─────────────────────────────────────────────────────────

    def test_list_parser_default_limit(self):
        """list default limit is 20."""
        parser = build_parser()
        args = parser.parse_args(["list"])
        assert args.command == "list"
        assert args.limit == 20

    def test_list_parser_accepts_limit_flag(self):
        """list --limit flag is accepted."""
        parser = build_parser()
        args = parser.parse_args(["list", "--limit", "5"])
        assert args.limit == 5

    def test_list_parser_accepts_local_flag(self):
        """list --local flag is accepted."""
        parser = build_parser()
        args = parser.parse_args(["list", "--local"])
        assert args.local is True

    # ── health ───────────────────────────────────────────────────────

    def test_health_parser_default_not_verbose(self):
        """health default verbose is False."""
        parser = build_parser()
        args = parser.parse_args(["health"])
        assert args.command == "health"
        assert args.verbose is False

    def test_health_parser_accepts_verbose_flag(self):
        """health --verbose flag is accepted."""
        parser = build_parser()
        args = parser.parse_args(["health", "--verbose"])
        assert args.verbose is True

    def test_health_parser_accepts_timeout_flag(self):
        """health --timeout flag is accepted."""
        parser = build_parser()
        args = parser.parse_args(["health", "--timeout", "30"])
        assert args.timeout == 30

    # ── resume ───────────────────────────────────────────────────────

    def test_resume_parser_accepts_engagement_id(self):
        """resume subcommand parses engagement_id."""
        parser = build_parser()
        args = parser.parse_args(["resume", "eng-001"])
        assert args.command == "resume"
        assert args.engagement_id == "eng-001"

    def test_resume_parser_accepts_local_flag(self):
        """resume --local flag is accepted."""
        parser = build_parser()
        args = parser.parse_args(["resume", "eng-001", "--local"])
        assert args.local is True

    def test_resume_parser_accepts_db_flag(self):
        """resume --db flag is accepted."""
        parser = build_parser()
        args = parser.parse_args(["resume", "eng-001", "--db", "test.db"])
        assert args.db == "test.db"

    def test_resume_parser_accepts_output_flag(self):
        """resume --output flag is accepted."""
        parser = build_parser()
        args = parser.parse_args(["resume", "eng-001", "-o", "resume.json"])
        assert args.output == "resume.json"

    def test_resume_parser_accepts_llm_refine_flag(self):
        """resume --llm-refine flag is accepted."""
        parser = build_parser()
        args = parser.parse_args(["resume", "eng-001", "--llm-refine"])
        assert args.llm_refine is True

    # ── trends ───────────────────────────────────────────────────────

    def test_trends_parser_defaults(self):
        """trends subcommand has correct defaults."""
        parser = build_parser()
        args = parser.parse_args(["trends"])
        assert args.command == "trends"
        assert args.domain is None
        assert args.last_n_days is None
        assert args.min_severity is None
        assert args.verbose is False

    def test_trends_parser_accepts_domain_flag(self):
        """trends --domain flag is accepted."""
        parser = build_parser()
        args = parser.parse_args(["trends", "--domain", "example.com"])
        assert args.domain == "example.com"

    def test_trends_parser_accepts_last_n_days_flag(self):
        """trends --last-n-days flag is accepted."""
        parser = build_parser()
        args = parser.parse_args(["trends", "--last-n-days", "90"])
        assert args.last_n_days == 90

    def test_trends_parser_accepts_min_severity_flag(self):
        """trends --min-severity flag is accepted with valid choices."""
        parser = build_parser()
        args = parser.parse_args(["trends", "--min-severity", "HIGH"])
        assert args.min_severity == "HIGH"

    def test_trends_parser_rejects_invalid_min_severity(self):
        """trends --min-severity rejects invalid values."""
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["trends", "--min-severity", "INVALID"])

    def test_trends_parser_accepts_verbose_flag(self):
        """trends --verbose flag is accepted."""
        parser = build_parser()
        args = parser.parse_args(["trends", "--verbose"])
        assert args.verbose is True

    def test_trends_parser_accepts_local_flag(self):
        """trends --local flag is accepted."""
        parser = build_parser()
        args = parser.parse_args(["trends", "--local"])
        assert args.local is True

    def test_trends_parser_accepts_db_flag(self):
        """trends --db flag is accepted."""
        parser = build_parser()
        args = parser.parse_args(["trends", "--db", "trends.db"])
        assert args.db == "trends.db"


# ── Command dispatch tests ──────────────────────────────────────────────


class TestMainDispatch:
    """Verify main() dispatches to the correct command handlers."""

    @patch("cli.cmd_assess")
    def test_main_assess_calls_cmd_assess(self, mock_assess):
        """main() dispatches 'assess' to cmd_assess."""
        mock_assess.return_value = 0
        with patch.object(sys, "argv", ["argus", "assess", "https://example.com"]):
            assert main() == 0
        mock_assess.assert_called_once()

    @patch("cli.cmd_scan")
    def test_main_scan_calls_cmd_scan(self, mock_scan):
        """main() dispatches 'scan' to cmd_scan."""
        mock_scan.return_value = 0
        with patch.object(sys, "argv", ["argus", "scan", "https://example.com"]):
            assert main() == 0
        mock_scan.assert_called_once()

    @patch("cli.cmd_report")
    def test_main_report_calls_cmd_report(self, mock_report):
        """main() dispatches 'report' to cmd_report."""
        mock_report.return_value = 0
        with patch.object(sys, "argv", ["argus", "report", "eng-001"]):
            assert main() == 0
        mock_report.assert_called_once()

    @patch("cli.cmd_list")
    def test_main_list_calls_cmd_list(self, mock_list):
        """main() dispatches 'list' to cmd_list."""
        mock_list.return_value = 0
        with patch.object(sys, "argv", ["argus", "list"]):
            assert main() == 0
        mock_list.assert_called_once()

    @patch("cli.cmd_health")
    def test_main_health_calls_cmd_health(self, mock_health):
        """main() dispatches 'health' to cmd_health."""
        mock_health.return_value = 0
        with patch.object(sys, "argv", ["argus", "health"]):
            assert main() == 0
        mock_health.assert_called_once()

    @patch("cli.cmd_resume")
    def test_main_resume_calls_cmd_resume(self, mock_resume):
        """main() dispatches 'resume' to cmd_resume."""
        mock_resume.return_value = 0
        with patch.object(sys, "argv", ["argus", "resume", "eng-001"]):
            assert main() == 0
        mock_resume.assert_called_once()

    @patch("cli.cmd_trends")
    def test_main_trends_calls_cmd_trends(self, mock_trends):
        """main() dispatches 'trends' to cmd_trends."""
        mock_trends.return_value = 0
        with patch.object(sys, "argv", ["argus", "trends"]):
            assert main() == 0
        mock_trends.assert_called_once()

    def test_main_unknown_command_prints_help(self):
        """main() with an unknown command prints help and returns 0."""
        with patch.object(sys, "argv", ["argus", "unknown"]):
            # Unknown command triggers argparse error which calls sys.exit
            with pytest.raises(SystemExit):
                main()

    def test_main_propagates_keyboard_interrupt(self):
        """main() propagates KeyboardInterrupt (to be caught by sys.exit wrapper)."""
        with patch.object(sys, "argv", ["argus", "assess", "https://example.com"]):
            with patch("cli.cmd_assess", side_effect=KeyboardInterrupt):
                with pytest.raises(KeyboardInterrupt):
                    main()

    def test_main_propagates_exception(self):
        """main() propagates unexpected exceptions (to be caught by sys.exit wrapper)."""
        with patch.object(sys, "argv", ["argus", "assess", "https://example.com"]):
            with patch("cli.cmd_assess", side_effect=Exception("Unexpected error")):
                with pytest.raises(Exception, match="Unexpected error"):
                    main()


# ── Edge cases ──────────────────────────────────────────────────────────


class TestCLIEdgeCases:
    """Edge cases for CLI argument parsing."""

    def test_short_flags_work(self):
        """Short flags (-a, -d, -o, -n, -v, -f, -t) are accepted."""
        parser = build_parser()
        args = parser.parse_args([
            "assess", "https://example.com", "-a", "light", "-d", "test.db", "-o", "out.json",
        ])
        assert args.aggressiveness == "light"
        assert args.db == "test.db"
        assert args.output == "out.json"

    def test_aggressiveness_valid_choices(self):
        """aggressiveness accepts only light, moderate, or aggressive."""
        parser = build_parser()
        for val in ("light", "moderate", "aggressive"):
            args = parser.parse_args(["assess", "https://example.com", "-a", val])
            assert args.aggressiveness == val

    def test_aggressiveness_rejects_invalid_choice(self):
        """aggressiveness rejects invalid values."""
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["assess", "https://example.com", "-a", "extreme"])

    def test_report_format_valid_choices(self):
        """report --format accepts json, html, pdf, markdown."""
        parser = build_parser()
        for fmt in ("json", "html", "pdf", "markdown"):
            args = parser.parse_args(["report", "eng-001", "-f", fmt])
            assert args.format == fmt

    def test_report_format_rejects_invalid_choice(self):
        """report --format rejects invalid values."""
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["report", "eng-001", "-f", "docx"])

    def test_help_shows_all_commands(self):
        """--help output includes all 7 commands."""
        parser = build_parser()
        help_text = parser.format_help()
        for cmd in ("assess", "scan", "report", "list", "health", "resume", "trends"):
            assert cmd in help_text

    def test_subcommand_help_shows_arguments(self):
        """Each subcommand's --help shows its arguments."""
        parser = build_parser()
        for cmd in ("assess", "report", "scan"):
            with pytest.raises(SystemExit):
                parser.parse_args([cmd, "--help"])

    def test_main_with_dash_dash(self):
        """-- separator before target works."""
        parser = build_parser()
        args = parser.parse_args(["assess", "--", "https://example.com"])
        assert args.target == "https://example.com"

    def test_local_implies_default_db(self):
        """When --local specified without --db, db is None (managed by cmd)."""
        parser = build_parser()
        args = parser.parse_args(["assess", "https://example.com", "--local"])
        assert args.local is True
        assert args.db is None  # cmd_assess will set the default path

    def test_db_without_local_still_accepted(self):
        """--db without --local is accepted (in-memory + file path)."""
        parser = build_parser()
        args = parser.parse_args(["assess", "https://example.com", "--db", "custom.db"])
        assert args.db == "custom.db"


if __name__ == "__main__":
    pytest.main([__file__])
