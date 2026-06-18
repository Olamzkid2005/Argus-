"""
Tests for utils/error_hints.py

Tests cover:
- hint_for_classification() with ErrorCode matches (most specific)
- hint_for_classification() with ErrorCategory fallback
- hint_for_classification() generic fallback
- Tool-specific stderr remediation hints
- build_error_hint() integration with error_classifier.py
- Edge cases: unclassifiable errors, None inputs, empty stderr
"""

from error_classifier import (
    CodeBasedClassification,
    ErrorCategory,
    ErrorCode,
    ErrorSeverity,
)
from utils.error_hints import (
    ErrorHint,
    _tool_specific_hint,
    build_error_hint,
    hint_for_classification,
)


class TestHintForClassification:
    """Tests for hint_for_classification() — core dispatcher."""

    def test_hint_by_error_code_config_not_found(self):
        """ErrorCode.CONFIG_NOT_FOUND returns config-specific hint."""
        classification = CodeBasedClassification(
            category=ErrorCategory.PERMANENT,
            severity=ErrorSeverity.HIGH,
            should_retry=False,
            retry_delay_seconds=0,
            alert_message="Config not found",
            error_code=ErrorCode.CONFIG_NOT_FOUND,
        )
        hint = hint_for_classification(
            classification,
            error=FileNotFoundError("argus.config.yaml not found"),
        )
        assert hint is not None
        assert "configuration" in hint.summary.lower()
        assert "argus.config.yaml" in hint.remediation.lower()
        assert hint.error_id == "CONFIG_NOT_FOUND"

    def test_hint_by_error_code_rate_limited(self):
        """ErrorCode.RATE_LIMITED returns aggressiveness hint."""
        classification = CodeBasedClassification(
            category=ErrorCategory.RATE_LIMIT,
            severity=ErrorSeverity.MEDIUM,
            should_retry=True,
            retry_delay_seconds=30,
            alert_message=None,
            error_code=ErrorCode.RATE_LIMITED,
        )
        hint = hint_for_classification(
            classification,
            error=Exception("429 Too Many Requests"),
            tool_name="nuclei",
        )
        assert hint is not None
        assert "rate" in hint.summary.lower()
        assert "--aggressiveness low" in hint.hint_command
        assert hint.tool == "nuclei"

    def test_hint_by_error_code_tool_timed_out(self):
        """ErrorCode.TOOL_TIMED_OUT returns timeout hint."""
        classification = CodeBasedClassification(
            category=ErrorCategory.TIMEOUT,
            severity=ErrorSeverity.MEDIUM,
            should_retry=True,
            retry_delay_seconds=60,
            alert_message=None,
            error_code=ErrorCode.TOOL_TIMED_OUT,
        )
        hint = hint_for_classification(
            classification,
            error=TimeoutError("nuclei timed out after 180s"),
            tool_name="nuclei",
        )
        assert hint is not None
        assert "time" in hint.summary.lower()
        assert "--timeout" in hint.remediation

    def test_hint_by_error_code_tool_not_found(self):
        """ErrorCode.TOOL_NOT_FOUND returns installation hint."""
        classification = CodeBasedClassification(
            category=ErrorCategory.PERMANENT,
            severity=ErrorSeverity.HIGH,
            should_retry=False,
            retry_delay_seconds=0,
            alert_message="Tool not found",
            error_code=ErrorCode.TOOL_NOT_FOUND,
        )
        hint = hint_for_classification(
            classification,
            error=FileNotFoundError("nuclei: not found"),
            tool_name="nuclei",
        )
        assert hint is not None
        assert "not found" in hint.summary.lower()
        assert "install" in hint.remediation.lower()

    def test_hint_by_error_code_target_unreachable(self):
        """ErrorCode.TARGET_UNREACHABLE returns connectivity hint."""
        classification = CodeBasedClassification(
            category=ErrorCategory.PERMANENT,
            severity=ErrorSeverity.HIGH,
            should_retry=False,
            retry_delay_seconds=0,
            alert_message="Target unreachable",
            error_code=ErrorCode.TARGET_UNREACHABLE,
        )
        hint = hint_for_classification(
            classification,
            error=ConnectionError("Connection refused"),
            target="https://example.com",
        )
        assert hint is not None
        assert "unreachable" in hint.summary.lower()
        assert "curl" in hint.hint_command

    def test_hint_by_error_code_dns_failure(self):
        """ErrorCode.DNS_RESOLUTION_FAILED returns DNS hint."""
        classification = CodeBasedClassification(
            category=ErrorCategory.PERMANENT,
            severity=ErrorSeverity.HIGH,
            should_retry=False,
            retry_delay_seconds=0,
            alert_message="DNS resolution failed",
            error_code=ErrorCode.DNS_RESOLUTION_FAILED,
        )
        hint = hint_for_classification(
            classification,
            error=Exception("Name or service not known"),
        )
        assert hint is not None
        assert "dns" in hint.summary.lower()
        assert "nslookup" in hint.hint_command

    def test_hint_by_error_code_database_error(self):
        """ErrorCode.DATABASE_ERROR returns DB connectivity hint."""
        classification = CodeBasedClassification(
            category=ErrorCategory.INFRASTRUCTURE,
            severity=ErrorSeverity.HIGH,
            should_retry=True,
            retry_delay_seconds=30,
            alert_message="Database error",
            error_code=ErrorCode.DATABASE_ERROR,
        )
        hint = hint_for_classification(
            classification,
            error=Exception("could not connect to database"),
        )
        assert hint is not None
        assert "database" in hint.summary.lower()
        assert "DATABASE_URL" in hint.remediation

    def test_hint_fallback_by_category_transient(self):
        """TRANSIENT category (no ErrorCode) returns transient hint."""
        classification = CodeBasedClassification(
            category=ErrorCategory.TRANSIENT,
            severity=ErrorSeverity.LOW,
            should_retry=True,
            retry_delay_seconds=30,
            alert_message=None,
            error_code=None,
        )
        hint = hint_for_classification(
            classification,
            error=Exception("Connection reset by peer"),
        )
        assert hint is not None
        assert "temporary" in hint.summary.lower()
        assert hint.error_id is None

    def test_hint_fallback_by_category_security(self):
        """SECURITY category (no ErrorCode) returns auth hint."""
        classification = CodeBasedClassification(
            category=ErrorCategory.SECURITY,
            severity=ErrorSeverity.CRITICAL,
            should_retry=False,
            retry_delay_seconds=0,
            alert_message="Unauthorized",
            error_code=None,
        )
        hint = hint_for_classification(
            classification,
            error=Exception("Authentication failed"),
        )
        assert hint is not None
        assert "authentication" in hint.summary.lower()
        assert "credentials" in hint.remediation.lower()

    def test_hint_fallback_by_category_unknown(self):
        """UNKNOWN category returns generic fallback."""
        classification = CodeBasedClassification(
            category=ErrorCategory.UNKNOWN,
            severity=ErrorSeverity.MEDIUM,
            should_retry=False,
            retry_delay_seconds=0,
            alert_message=None,
            error_code=None,
        )
        hint = hint_for_classification(
            classification,
            error=Exception("Something weird happened"),
        )
        assert hint is not None
        assert "unknown" in hint.summary.lower()

    def test_hint_returns_none_for_none_classification(self):
        """None classification returns None (no crash)."""
        hint = hint_for_classification(None, error=Exception("test"))
        assert hint is None

    def test_hint_preserves_tool_name(self):
        """Tool name is preserved in the hint."""
        classification = CodeBasedClassification(
            category=ErrorCategory.RATE_LIMIT,
            severity=ErrorSeverity.MEDIUM,
            should_retry=True,
            retry_delay_seconds=30,
            alert_message=None,
            error_code=ErrorCode.RATE_LIMITED,
        )
        hint = hint_for_classification(
            classification,
            error=Exception("429"),
            tool_name="nuclei",
        )
        assert hint.tool == "nuclei"


class TestToolSpecificHints:
    """Tests for _tool_specific_hint() — stderr pattern matching."""

    def test_nuclei_templates_not_found(self):
        """Nuclei 'templates not found' stderr returns template hint."""
        hint = _tool_specific_hint(
            "nuclei",
            1,
            "Error: templates not found. Please run nuclei -update-templates",
        )
        assert hint is not None
        assert "template" in hint.summary.lower()
        assert "nuclei -update-templates" in hint.hint_command

    def test_nmap_permission_error(self):
        """Nmap 'requires root privileges' stderr returns sudo hint."""
        hint = _tool_specific_hint(
            "nmap",
            1,
            "You don't have root privileges. Nmap requires root for SYN scan.",
        )
        assert hint is not None
        assert "permission" in hint.summary.lower()
        assert "sudo" in hint.hint_command

    def test_sqlmap_no_injectable_parameters(self):
        """SQLmap 'no injectable' stderr returns hint."""
        hint = _tool_specific_hint(
            "sqlmap",
            0,
            "No parameter found. Try to specify parameters manually.",
        )
        assert hint is not None
        assert "injectable" in hint.summary.lower()

    def test_semgrep_rules_not_found(self):
        """Semgrep 'no rules found' stderr returns config hint."""
        hint = _tool_specific_hint(
            "semgrep",
            1,
            "No rules found. Specify rules with --config",
        )
        assert hint is not None
        assert "rule" in hint.summary.lower()
        assert "--config" in hint.remediation

    def test_gitleaks_no_git_repo(self):
        """Gitleaks no git repo stderr returns --no-git hint."""
        hint = _tool_specific_hint(
            "gitleaks",
            1,
            "No git repository found in current directory",
        )
        assert hint is not None
        assert "git" in hint.summary.lower()
        assert "--no-git" in hint.remediation

    def test_unknown_tool_returns_none(self):
        """Unknown tool name returns None (no crash)."""
        hint = _tool_specific_hint(
            "unknown_tool",
            1,
            "Some error message",
        )
        assert hint is None

    def test_empty_stderr_returns_none(self):
        """Empty stderr returns None."""
        hint = _tool_specific_hint("nuclei", 1, "")
        assert hint is None

    def test_no_match_returns_none(self):
        """Non-matching stderr returns None."""
        hint = _tool_specific_hint(
            "nuclei",
            1,
            "Some unrelated error message",
        )
        assert hint is None


class TestBuildErrorHint:
    """Tests for build_error_hint() — primary entry point."""

    def test_build_with_error_code(self):
        """build_error_hint with ErrorCode returns correct hint."""
        error = FileNotFoundError("nuclei not found")
        hint = build_error_hint(
            error,
            error_code=ErrorCode.TOOL_NOT_FOUND,
            tool_name="nuclei",
        )
        assert hint is not None
        assert hint.tool == "nuclei"
        assert hint.error_id == "TOOL_NOT_FOUND"
        assert "not found" in hint.summary.lower()

    def test_build_without_error_code_fallback(self):
        """build_error_hint without ErrorCode falls back to string matching."""
        error = Exception("429 Too Many Requests: rate limit exceeded")
        hint = build_error_hint(
            error,
            tool_name="nuclei",
        )
        assert hint is not None
        assert "rate" in hint.summary.lower()

    def test_build_with_tool_specific_stderr(self):
        """build_error_hint with tool stderr merges tool-specific hint."""
        error = Exception("Tool execution failed")
        hint = build_error_hint(
            error,
            error_code=ErrorCode.TOOL_EXECUTION_FAILED,
            tool_name="nuclei",
            stderr="Error: templates not found. Please run nuclei -update-templates",
            exit_code=1,
        )
        assert hint is not None
        # Should have merged tool-specific remediation over generic
        assert "template" in hint.remediation.lower()

    def test_build_unclassifiable_returns_none_gracefully(self):
        """build_error_hint for truly unclassifiable error returns None gracefully."""
        # Use a very weird error that doesn't match any pattern
        error = Exception("xyz123_nonexistent_error_type_abc")
        hint = build_error_hint(error)
        # Should still get the generic fallback, not crash
        assert hint is not None
        assert hint.summary is not None

    def test_build_no_crash_on_internal_error(self):
        """build_error_hint never crashes even with unexpected input."""
        # Pass a non-Exception object to trigger the error path
        hint = build_error_hint("not an exception")  # type: ignore[arg-type]
        # Should still not crash — returns generic hint or None
        # The important thing is no exception is raised
        assert hint is None or isinstance(hint.summary, str)

    def test_build_with_target_context(self):
        """build_error_hint passes target context through."""
        error = ConnectionError("Connection refused")
        hint = build_error_hint(
            error,
            error_code=ErrorCode.TARGET_UNREACHABLE,
            target="https://example.com",
        )
        assert hint is not None
        assert hint.error_id == "TARGET_UNREACHABLE"


class TestErrorHintToDict:
    """Tests for ErrorHint.to_dict() serialization."""

    def test_to_dict_full(self):
        """to_dict returns all fields."""
        hint = ErrorHint(
            summary="Test summary",
            detail="Test detail",
            remediation="Test remediation",
            hint_command="test --help",
            docs_url="https://docs.example.com",
            tool="nuclei",
            error_id="TOOL_NOT_FOUND",
        )
        d = hint.to_dict()
        assert d["summary"] == "Test summary"
        assert d["detail"] == "Test detail"
        assert d["remediation"] == "Test remediation"
        assert d["hint_command"] == "test --help"
        assert d["docs_url"] == "https://docs.example.com"
        assert d["tool"] == "nuclei"
        assert d["error_id"] == "TOOL_NOT_FOUND"

    def test_to_dict_empty(self):
        """to_dict with default values."""
        hint = ErrorHint(summary="Test")
        d = hint.to_dict()
        assert d["summary"] == "Test"
        assert d["detail"] == ""
        assert d["remediation"] == ""
        assert d["hint_command"] is None
        assert d["docs_url"] is None
        assert d["tool"] is None
        assert d["error_id"] is None
