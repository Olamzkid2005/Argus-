"""
Tests for runtime/preflight.py — Consolidated Startup Preflight Check.

Covers:
  - CheckResult dataclass
  - PreflightReport dataclass (auto-counts, properties, summary, to_dict, log_summary)
  - Each individual check function (with mocked env vars and imports)
  - run_preflight() (filters, exception handling)
  - display_preflight_report() (verbose/non-verbose, all-pass, mixed)
"""

import os
import sys

import pytest

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# ═══════════════════════════════════════════════════════════════════════
# CheckResult
# ═══════════════════════════════════════════════════════════════════════


class TestCheckResult:
    """Test the CheckResult dataclass."""

    def test_minimal_construction(self):
        """CheckResult can be created with just name, severity, message."""
        from runtime.preflight import CheckResult

        result = CheckResult(name="test", severity="ok", message="All good")
        assert result.name == "test"
        assert result.severity == "ok"
        assert result.message == "All good"
        assert result.detail == ""

    def test_with_detail(self):
        """CheckResult with optional detail."""
        from runtime.preflight import CheckResult

        result = CheckResult(
            name="test", severity="error", message="Failed", detail="Something broke"
        )
        assert result.detail == "Something broke"


# ═══════════════════════════════════════════════════════════════════════
# PreflightReport
# ═══════════════════════════════════════════════════════════════════════


class TestPreflightReport:
    """Test the PreflightReport dataclass."""

    def test_empty_report(self):
        """Empty report has zero counts."""
        from runtime.preflight import PreflightReport

        report = PreflightReport()
        assert report.total == 0
        assert report.ok_count == 0
        assert report.warning_count == 0
        assert report.error_count == 0
        assert report.has_errors() is False
        assert report.has_warnings() is False
        assert report.summary == "no checks run"

    def test_auto_counts_from_checks(self):
        """Report auto-computes counts from checks list."""
        from runtime.preflight import PreflightReport, CheckResult, CheckSeverity

        checks = [
            CheckResult(name="a", severity=CheckSeverity.OK, message="ok"),
            CheckResult(name="b", severity=CheckSeverity.WARNING, message="warn"),
            CheckResult(name="c", severity=CheckSeverity.ERROR, message="err"),
            CheckResult(name="d", severity=CheckSeverity.OK, message="ok2"),
        ]
        report = PreflightReport(checks=checks)
        assert report.total == 4
        assert report.ok_count == 2
        assert report.warning_count == 1
        assert report.error_count == 1
        assert report.has_errors() is True
        assert report.has_warnings() is True

    def test_errors_property(self):
        """errors property returns only ERROR checks."""
        from runtime.preflight import PreflightReport, CheckResult, CheckSeverity

        checks = [
            CheckResult(name="a", severity=CheckSeverity.OK, message="ok"),
            CheckResult(name="b", severity=CheckSeverity.ERROR, message="err1"),
            CheckResult(name="c", severity=CheckSeverity.ERROR, message="err2"),
        ]
        report = PreflightReport(checks=checks)
        assert len(report.errors) == 2
        assert all(e.severity == CheckSeverity.ERROR for e in report.errors)
        assert [e.name for e in report.errors] == ["b", "c"]

    def test_warnings_property(self):
        """warnings property returns only WARNING checks."""
        from runtime.preflight import PreflightReport, CheckResult, CheckSeverity

        checks = [
            CheckResult(name="a", severity=CheckSeverity.WARNING, message="w1"),
            CheckResult(name="b", severity=CheckSeverity.OK, message="ok"),
            CheckResult(name="c", severity=CheckSeverity.WARNING, message="w2"),
        ]
        report = PreflightReport(checks=checks)
        assert len(report.warnings) == 2
        assert all(w.severity == CheckSeverity.WARNING for w in report.warnings)
        assert [w.name for w in report.warnings] == ["a", "c"]

    def test_summary_mixed(self):
        """Summary with mixed results."""
        from runtime.preflight import PreflightReport, CheckResult, CheckSeverity

        checks = [
            CheckResult(name="a", severity=CheckSeverity.OK, message=""),
            CheckResult(name="b", severity=CheckSeverity.WARNING, message=""),
            CheckResult(name="c", severity=CheckSeverity.ERROR, message=""),
        ]
        report = PreflightReport(checks=checks)
        summary = report.summary
        assert "1 ok" in summary
        assert "1 warning(s)" in summary
        assert "1 error(s)" in summary
        assert "(3 total)" in summary

    def test_summary_all_ok(self):
        """Summary with all OK."""
        from runtime.preflight import PreflightReport, CheckResult, CheckSeverity

        checks = [
            CheckResult(name="a", severity=CheckSeverity.OK, message=""),
            CheckResult(name="b", severity=CheckSeverity.OK, message=""),
        ]
        report = PreflightReport(checks=checks)
        summary = report.summary
        assert "2 ok" in summary
        assert "warning" not in summary
        assert "error" not in summary

    def test_to_dict(self):
        """to_dict returns expected dict shape."""
        from runtime.preflight import PreflightReport, CheckResult, CheckSeverity

        checks = [
            CheckResult(name="test_check", severity=CheckSeverity.OK, message="All good"),
            CheckResult(
                name="warn_check",
                severity=CheckSeverity.WARNING,
                message="Watch out",
                detail="Something to watch",
            ),
        ]
        report = PreflightReport(checks=checks)
        d = report.to_dict()

        assert d["total"] == 2
        assert d["ok"] == 1
        assert d["warnings"] == 1
        assert d["errors"] == 0
        assert len(d["checks"]) == 2
        assert d["checks"][0]["name"] == "test_check"
        assert d["checks"][0]["severity"] == "ok"
        assert d["checks"][1]["name"] == "warn_check"
        assert d["checks"][1]["detail"] == "Something to watch"


# ═══════════════════════════════════════════════════════════════════════
# Individual check functions
# ═══════════════════════════════════════════════════════════════════════


class TestCheckSettingsEncryptionKey:
    """Test _check_settings_encryption_key()."""

    def test_key_set_returns_ok(self):
        """When SETTINGS_ENCRYPTION_KEY is set, returns OK."""
        from runtime.preflight import _check_settings_encryption_key, CheckSeverity

        os.environ["SETTINGS_ENCRYPTION_KEY"] = "test-key"
        try:
            result = _check_settings_encryption_key()
            assert result.severity == CheckSeverity.OK
            assert "is set" in result.message
        finally:
            del os.environ["SETTINGS_ENCRYPTION_KEY"]

    def test_key_missing_returns_error(self):
        """When SETTINGS_ENCRYPTION_KEY is not set, returns ERROR."""
        from runtime.preflight import _check_settings_encryption_key, CheckSeverity

        # Ensure it's not set
        os.environ.pop("SETTINGS_ENCRYPTION_KEY", None)
        result = _check_settings_encryption_key()
        assert result.severity == CheckSeverity.ERROR
        assert "not set" in result.message


class TestCheckAuthCheckpointKey:
    """Test _check_auth_checkpoint_key()."""

    def test_key_set_and_valid_returns_ok(self):
        """When AUTH_CHECKPOINT_KEY is a valid Fernet key, returns OK."""
        from runtime.preflight import _check_auth_checkpoint_key, CheckSeverity
        from cryptography.fernet import Fernet

        valid_key = Fernet.generate_key().decode()
        os.environ["AUTH_CHECKPOINT_KEY"] = valid_key
        try:
            result = _check_auth_checkpoint_key()
            assert result.severity == CheckSeverity.OK
            assert "set and valid" in result.message
        finally:
            del os.environ["AUTH_CHECKPOINT_KEY"]

    def test_key_missing_returns_warning(self):
        """When AUTH_CHECKPOINT_KEY is not set, returns WARNING."""
        from runtime.preflight import _check_auth_checkpoint_key, CheckSeverity

        os.environ.pop("AUTH_CHECKPOINT_KEY", None)
        result = _check_auth_checkpoint_key()
        assert result.severity == CheckSeverity.WARNING
        assert "not set" in result.message

    def test_key_invalid_returns_error(self):
        """When AUTH_CHECKPOINT_KEY is not a valid Fernet key, returns ERROR."""
        from runtime.preflight import _check_auth_checkpoint_key, CheckSeverity

        os.environ["AUTH_CHECKPOINT_KEY"] = "not-a-valid-fernet-key"
        try:
            result = _check_auth_checkpoint_key()
            assert result.severity == CheckSeverity.ERROR
            assert "invalid" in result.message.lower()
        finally:
            del os.environ["AUTH_CHECKPOINT_KEY"]


class TestCheckScopeConfig:
    """Test _check_scope_config()."""

    def test_not_autonomous_returns_ok(self):
        """When not in autonomous mode, returns OK."""
        from runtime.preflight import _check_scope_config, CheckSeverity

        os.environ.pop("ARGUS_AUTONOMOUS", None)
        os.environ.pop("ARGUS_ALLOW_UNSCOPED", None)
        result = _check_scope_config()
        assert result.severity == CheckSeverity.OK

    def test_autonomous_no_unscoped_returns_warning(self):
        """Autonomous mode without ARGUS_ALLOW_UNSCOPED returns WARNING."""
        from runtime.preflight import _check_scope_config, CheckSeverity

        os.environ["ARGUS_AUTONOMOUS"] = "1"
        os.environ.pop("ARGUS_ALLOW_UNSCOPED", None)
        try:
            result = _check_scope_config()
            assert result.severity == CheckSeverity.WARNING
            assert "without" in result.message.lower()
        finally:
            del os.environ["ARGUS_AUTONOMOUS"]

    def test_autonomous_with_unscoped_returns_warning(self):
        """Autonomous mode with ARGUS_ALLOW_UNSCOPED returns WARNING."""
        from runtime.preflight import _check_scope_config, CheckSeverity

        os.environ["ARGUS_AUTONOMOUS"] = "1"
        os.environ["ARGUS_ALLOW_UNSCOPED"] = "1"
        try:
            result = _check_scope_config()
            assert result.severity == CheckSeverity.WARNING
            assert "bypassed" in result.message.lower()
        finally:
            del os.environ["ARGUS_AUTONOMOUS"]
            del os.environ["ARGUS_ALLOW_UNSCOPED"]


class TestCheckDNS:
    """Test _check_dns()."""

    def test_returns_result(self):
        """_check_dns returns a CheckResult (either OK or WARNING)."""
        from runtime.preflight import _check_dns, CheckSeverity

        result = _check_dns()
        # DNS may or may not work in CI — both are valid outcomes
        assert result.severity in (CheckSeverity.OK, CheckSeverity.WARNING)
        assert result.name == "dns_resolution"


class TestCheckLLMConfig:
    """Test _check_llm_config()."""

    def test_no_keys_returns_warning(self):
        """When no LLM keys are configured, returns WARNING."""
        from runtime.preflight import _check_llm_config, CheckSeverity

        # Save and clear relevant keys
        saved = {}
        for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
                     "OPENROUTER_API_KEY", "AZURE_OPENAI_API_KEY", "LLM_API_KEY"):
            saved[key] = os.environ.pop(key, None)

        try:
            result = _check_llm_config()
            assert result.severity == CheckSeverity.WARNING
            assert "No LLM API keys" in result.message
        finally:
            for key, val in saved.items():
                if val is not None:
                    os.environ[key] = val

    def test_with_openai_key_returns_ok(self):
        """When OPENAI_API_KEY is set, returns OK."""
        from runtime.preflight import _check_llm_config, CheckSeverity

        os.environ["OPENAI_API_KEY"] = "sk-test-key-12345"
        try:
            result = _check_llm_config()
            assert result.severity == CheckSeverity.OK
            assert "OpenAI" in result.message
        finally:
            del os.environ["OPENAI_API_KEY"]

    def test_with_placeholder_key_returns_warning(self):
        """When key starts with 'your_', treats as unconfigured."""
        from runtime.preflight import _check_llm_config, CheckSeverity

        os.environ["OPENAI_API_KEY"] = "your_key_here"
        try:
            result = _check_llm_config()
            assert result.severity == CheckSeverity.WARNING
        finally:
            del os.environ["OPENAI_API_KEY"]


class TestCheckDatabaseURL:
    """Test _check_database_url()."""

    def test_url_set_returns_ok(self):
        """When DATABASE_URL is set, returns OK."""
        from runtime.preflight import _check_database_url, CheckSeverity

        os.environ["DATABASE_URL"] = "postgresql://user:pass@localhost:5432/db"
        try:
            result = _check_database_url()
            assert result.severity == CheckSeverity.OK
            assert "is set" in result.message
        finally:
            del os.environ["DATABASE_URL"]

    def test_url_set_masks_credentials(self):
        """DATABASE_URL message masks credentials."""
        from runtime.preflight import _check_database_url

        os.environ["DATABASE_URL"] = "postgresql://user:secret123@localhost:5432/db"
        try:
            result = _check_database_url()
            assert "secret123" not in result.message
            assert "***" in result.message
        finally:
            del os.environ["DATABASE_URL"]

    def test_url_missing_returns_warning(self):
        """When DATABASE_URL is not set, returns WARNING."""
        from runtime.preflight import _check_database_url, CheckSeverity

        os.environ.pop("DATABASE_URL", None)
        result = _check_database_url()
        assert result.severity == CheckSeverity.WARNING
        assert "not set" in result.message


class TestCheckPlaceholderCredentials:
    """Test _check_placeholder_credentials()."""

    def test_no_placeholders_returns_ok(self):
        """When no placeholder credentials are detected, returns OK."""
        from runtime.preflight import _check_placeholder_credentials, CheckSeverity

        # Save all env vars that check_placeholder_credentials() inspects
        # and set them all to non-placeholder values
        _PLACEHOLDER_CHECKED_KEYS = [
            "POSTGRES_PASSWORD", "POSTGRES_USER", "JWT_SECRET",
            "REDIS_PASSWORD", "OPENAI_API_KEY", "LLM_API_KEY",
            "ANTHROPIC_API_KEY",
        ]
        saved = {}
        for key in _PLACEHOLDER_CHECKED_KEYS:
            saved[key] = os.environ.pop(key, None)
            # Use values that pass all checks (JWT_SECRET must be >= 32 chars)
            if key == "JWT_SECRET":
                os.environ[key] = "a" * 32  # minimum 32 chars
            else:
                os.environ[key] = f"real_value_{key.lower()}_123"
        try:
            result = _check_placeholder_credentials()
            assert result.severity == CheckSeverity.OK
        finally:
            for key in _PLACEHOLDER_CHECKED_KEYS:
                del os.environ[key]
                if saved[key] is not None:
                    os.environ[key] = saved[key]

    def test_placeholder_detected(self):
        """When placeholder is found, returns WARNING (non-autonomous)."""
        from runtime.preflight import _check_placeholder_credentials, CheckSeverity

        saved_pw = os.environ.pop("POSTGRES_PASSWORD", None)
        saved_auto = os.environ.pop("ARGUS_AUTONOMOUS", None)
        os.environ["POSTGRES_PASSWORD"] = "change_me_in_production"
        try:
            result = _check_placeholder_credentials()
            assert result.severity == CheckSeverity.WARNING
        finally:
            del os.environ["POSTGRES_PASSWORD"]
            if saved_pw is not None:
                os.environ["POSTGRES_PASSWORD"] = saved_pw
            if saved_auto is not None:
                os.environ["ARGUS_AUTONOMOUS"] = saved_auto

    def test_placeholder_in_autonomous_returns_error(self):
        """Placeholder in autonomous mode returns ERROR."""
        from runtime.preflight import _check_placeholder_credentials, CheckSeverity

        saved_pw = os.environ.pop("POSTGRES_PASSWORD", None)
        saved_auto = os.environ.pop("ARGUS_AUTONOMOUS", None)
        os.environ["POSTGRES_PASSWORD"] = "change_me_in_production"
        os.environ["ARGUS_AUTONOMOUS"] = "1"
        try:
            result = _check_placeholder_credentials()
            assert result.severity == CheckSeverity.ERROR
        finally:
            del os.environ["POSTGRES_PASSWORD"]
            del os.environ["ARGUS_AUTONOMOUS"]
            if saved_pw is not None:
                os.environ["POSTGRES_PASSWORD"] = saved_pw
            if saved_auto is not None:
                os.environ["ARGUS_AUTONOMOUS"] = saved_auto


# ═══════════════════════════════════════════════════════════════════════
# run_preflight()
# ═══════════════════════════════════════════════════════════════════════


class TestRunPreflight:
    """Test run_preflight()."""

    @pytest.mark.slow(reason="Runs all 9 checks including DNS and tool health probes")
    def test_runs_all_checks(self):
        """run_preflight() runs all default checks and returns a report."""
        from runtime.preflight import run_preflight

        report = run_preflight()
        assert report.total == 9  # 9 default checks
        # At least some checks should complete (exact ok/warning/error depends on env)
        assert report.ok_count + report.warning_count + report.error_count == 9

    def test_include_checks_filter(self):
        """include_checks limits which checks run."""
        from runtime.preflight import run_preflight

        report = run_preflight(include_checks=["dns_resolution", "database_url"])
        assert report.total == 2
        assert report.checks[0].name == "dns_resolution"
        assert report.checks[1].name == "database_url"

    def test_exclude_checks_filter(self):
        """exclude_checks skips specified checks."""
        from runtime.preflight import run_preflight

        report = run_preflight(exclude_checks=["tool_health"])
        assert report.total == 8  # 9 - 1
        names = [c.name for c in report.checks]
        assert "tool_health" not in names
        assert "dns_resolution" in names

    def test_include_empty_returns_empty_report(self):
        """include_checks with empty list returns empty report."""
        from runtime.preflight import run_preflight

        report = run_preflight(include_checks=[])
        assert report.total == 0
        assert report.checks == []


# ═══════════════════════════════════════════════════════════════════════
# display_preflight_report()
# ═══════════════════════════════════════════════════════════════════════


class TestDisplayPreflightReport:
    """Test display_preflight_report()."""

    def test_all_pass_non_verbose_shows_success(self):
        """When all checks pass in non-verbose mode, shows success message."""
        from runtime.preflight import (
            PreflightReport,
            CheckResult,
            CheckSeverity,
            display_preflight_report,
        )

        checks = [
            CheckResult(name="a", severity=CheckSeverity.OK, message="ok"),
            CheckResult(name="b", severity=CheckSeverity.OK, message="ok"),
        ]
        report = PreflightReport(checks=checks)
        output = display_preflight_report(report, verbose=False)
        assert "All 2 preflight checks passed!" in output
        assert "2 ok" in output

    def test_mixed_results_non_verbose_shows_warnings_and_errors(self):
        """Non-verbose shows only non-OK checks."""
        from runtime.preflight import (
            PreflightReport,
            CheckResult,
            CheckSeverity,
            display_preflight_report,
        )

        checks = [
            CheckResult(name="ok_check", severity=CheckSeverity.OK, message="All good"),
            CheckResult(name="warn_check", severity=CheckSeverity.WARNING, message="Watch out"),
            CheckResult(name="err_check", severity=CheckSeverity.ERROR, message="Failed"),
        ]
        report = PreflightReport(checks=checks)
        output = display_preflight_report(report, verbose=False)
        assert "warn_check" in output
        assert "err_check" in output
        assert "ok_check" not in output  # hidden in non-verbose
        assert "WARNING" in output
        assert "ERROR" in output

    def test_verbose_shows_all(self):
        """Verbose mode shows all checks including OK."""
        from runtime.preflight import (
            PreflightReport,
            CheckResult,
            CheckSeverity,
            display_preflight_report,
        )

        checks = [
            CheckResult(name="ok_check", severity=CheckSeverity.OK, message="All good"),
            CheckResult(name="warn_check", severity=CheckSeverity.WARNING, message="Watch out"),
        ]
        report = PreflightReport(checks=checks)
        output = display_preflight_report(report, verbose=True)
        assert "ok_check" in output
        assert "warn_check" in output

    def test_errors_sorted_first(self):
        """Errors appear before warnings and OK in output."""
        from runtime.preflight import (
            PreflightReport,
            CheckResult,
            CheckSeverity,
            display_preflight_report,
        )

        checks = [
            CheckResult(name="warn_check", severity=CheckSeverity.WARNING, message="Watch out"),
            CheckResult(name="err_check", severity=CheckSeverity.ERROR, message="Failed"),
            CheckResult(name="ok_check", severity=CheckSeverity.OK, message="All good"),
        ]
        report = PreflightReport(checks=checks)
        output = display_preflight_report(report, verbose=True)
        # Find positions of each status in output
        err_pos = output.find("ERROR")
        warn_pos = output.find("WARNING")
        ok_pos = output.find("OK")
        assert err_pos < warn_pos, "Errors should appear before warnings"
        assert warn_pos < ok_pos, "Warnings should appear before OK"

    def test_detail_lines_in_non_verbose(self):
        """Long detail strings are shown below the table in non-verbose mode."""
        from runtime.preflight import (
            PreflightReport,
            CheckResult,
            CheckSeverity,
            display_preflight_report,
        )

        checks = [
            CheckResult(
                name="verbose_check",
                severity=CheckSeverity.WARNING,
                message="Something to watch",
                detail="A" * 50,  # 50 chars — longer than 33
            ),
        ]
        report = PreflightReport(checks=checks)
        output = display_preflight_report(report, verbose=False)
        assert "verbose_check:" in output
        assert "A" * 50 in output


# ═══════════════════════════════════════════════════════════════════════
# Integration: run_preflight -> display_preflight_report
# ═══════════════════════════════════════════════════════════════════════


class TestPreflightIntegration:
    """End-to-end integration between run_preflight and display."""

    @pytest.mark.slow(reason="Runs all 9 checks including DNS and tool health probes")
    def test_run_and_display_verbose(self):
        """Running preflight and displaying in verbose mode works end-to-end."""
        from runtime.preflight import run_preflight, display_preflight_report

        report = run_preflight()
        output = display_preflight_report(report, verbose=True)
        assert "Preflight Configuration Check" in output
        assert str(report.total) in output
        # All check names should appear in verbose output
        for check in report.checks:
            assert check.name in output

    @pytest.mark.slow(reason="Runs all 9 checks including DNS and tool health probes")
    def test_run_and_display_non_verbose(self):
        """Running preflight and displaying in non-verbose mode works."""
        from runtime.preflight import run_preflight, display_preflight_report

        report = run_preflight()
        output = display_preflight_report(report, verbose=False)
        assert "Preflight Configuration Check" in output
        # Non-verbose should only show non-OK checks
        for check in report.checks:
            if check.severity == "ok":
                assert check.name not in output
            else:
                assert check.name in output
