"""Tests for tool_core/result.py — UnifiedToolResult and ToolStatus."""

from datetime import datetime

import pytest

from tool_core.result import ToolStatus, UnifiedToolResult


class TestToolStatus:
    def test_is_fatal_statuses(self):
        assert ToolStatus.NOT_INSTALLED.is_fatal is True
        assert ToolStatus.IMPORT_ERROR.is_fatal is True
        assert ToolStatus.EXCEPTION.is_fatal is True
        assert ToolStatus.TIMEOUT.is_fatal is True

    def test_non_fatal_statuses(self):
        assert ToolStatus.SUCCESS.is_fatal is False
        assert ToolStatus.SUCCESS_EMPTY.is_fatal is False
        assert ToolStatus.NONZERO_EXIT.is_fatal is False
        assert ToolStatus.SKIPPED.is_fatal is False

    def test_is_ok(self):
        assert ToolStatus.SUCCESS.is_ok is True
        assert ToolStatus.SUCCESS_EMPTY.is_ok is True
        assert ToolStatus.TIMEOUT.is_ok is False
        assert ToolStatus.EXCEPTION.is_ok is False


class TestUnifiedToolResult:
    def test_default_construction(self):
        result = UnifiedToolResult(tool_name="nuclei")
        assert result.tool_name == "nuclei"
        assert result.command == []
        assert result.target == ""
        assert result.status == ToolStatus.EXCEPTION
        assert result.findings == []
        assert result.findings_count == 0
        assert result.ports == []
        assert result.open_ports_count == 0

    def test_mark_finished_sets_timing(self):
        result = UnifiedToolResult(tool_name="test")
        assert result.finished_at is None
        assert result.duration_seconds == 0.0
        result.mark_finished()
        assert result.finished_at is not None
        assert result.duration_seconds >= 0.0

    def test_mark_finished_counts_findings(self):
        result = UnifiedToolResult(tool_name="test")
        result.findings = [{"type": "XSS"}, {"type": "SQLI"}]
        result.mark_finished()
        assert result.findings_count == 2

    def test_not_installed_classmethod(self):
        result = UnifiedToolResult.not_installed("nuclei", ["nuclei", "-u", "target"])
        assert result.tool_name == "nuclei"
        assert result.status == ToolStatus.NOT_INSTALLED
        assert "not found on PATH" in result.error_message
        assert result.fix_hint != ""

    def test_from_exception(self):
        exc = RuntimeError("test error")
        result = UnifiedToolResult.from_exception("nuclei", ["nuclei"], exc)
        assert result.tool_name == "nuclei"
        assert result.status == ToolStatus.EXCEPTION
        assert result.error_type == "RuntimeError"
        assert result.error_message == "test error"
        assert result.finished_at is not None

    def test_from_exception_module_not_found(self):
        exc = ModuleNotFoundError("No module named 'requests'")
        result = UnifiedToolResult.from_exception("tool", ["tool"], exc)
        assert result.status == ToolStatus.IMPORT_ERROR
        assert "ModuleNotFoundError" in result.error_type

    def test_timeout_classmethod(self):
        result = UnifiedToolResult(
            tool_name="nuclei",
            command=["nuclei"],
            status=ToolStatus.TIMEOUT,
            error_type="TimeoutExpired",
            error_message="nuclei' exceeded time limit of 300s.",
        )
        result.mark_finished()
        assert result.status == ToolStatus.TIMEOUT
        assert "time limit" in result.error_message
        assert result.finished_at is not None

    def test_skipped_classmethod(self):
        result = UnifiedToolResult.skipped("nuclei", "Target out of scope", "https://example.com")
        assert result.tool_name == "nuclei"
        assert result.status == ToolStatus.SKIPPED
        assert result.target == "https://example.com"

    def test_to_report_dict_success(self):
        result = UnifiedToolResult(tool_name="nuclei", target="https://example.com")
        result.status = ToolStatus.SUCCESS
        result.mark_finished()
        d = result.to_report_dict()
        assert d["tool"] == "nuclei"
        assert d["status"] == "success"
        assert d["target"] == "https://example.com"
        assert "error" not in d

    def test_to_report_dict_with_error(self):
        result = UnifiedToolResult(tool_name="nuclei")
        result.status = ToolStatus.NONZERO_EXIT
        result.error_type = "ExitCodeError"
        result.error_message = "exit code 1"
        d = result.to_report_dict()
        assert "error" in d
        assert d["error"]["type"] == "ExitCodeError"

    def test_str_success(self):
        result = UnifiedToolResult(tool_name="nuclei")
        result.status = ToolStatus.SUCCESS
        s = str(result)
        assert "✅" in s
        assert "nuclei" in s

    def test_str_error(self):
        result = UnifiedToolResult(tool_name="nuclei")
        result.status = ToolStatus.EXCEPTION
        result.error_message = "failed"
        s = str(result)
        assert "❌" in s
        assert "failed" in s

    def test_str_with_findings(self):
        result = UnifiedToolResult(tool_name="nuclei")
        result.status = ToolStatus.SUCCESS
        result.findings = [{"type": "XSS"}]
        result.mark_finished()
        s = str(result)
        assert "1 finding" in s


class TestBackwardCompatProperties:
    def test_success(self):
        r = UnifiedToolResult(tool_name="test", status=ToolStatus.SUCCESS)
        assert r.success is True

    def test_success_false(self):
        r = UnifiedToolResult(tool_name="test", status=ToolStatus.EXCEPTION)
        assert r.success is False

    def test_returncode(self):
        r = UnifiedToolResult(tool_name="test", exit_code=1)
        assert r.returncode == 1

    def test_tool(self):
        r = UnifiedToolResult(tool_name="nuclei")
        assert r.tool == "nuclei"

    def test_error(self):
        r = UnifiedToolResult(tool_name="test", error_message="something broke")
        assert r.error == "something broke"

    def test_error_none(self):
        r = UnifiedToolResult(tool_name="test")
        assert r.error is None

    def test_duration_ms(self):
        r = UnifiedToolResult(tool_name="test")
        r.duration_seconds = 2.5
        assert r.duration_ms == 2500

    def test_timeout_true(self):
        r = UnifiedToolResult(tool_name="test", status=ToolStatus.TIMEOUT)
        assert r.timeout is True

    def test_timeout_false(self):
        r = UnifiedToolResult(tool_name="test", status=ToolStatus.SUCCESS)
        assert r.timeout is False

    def test_trace_id(self):
        r = UnifiedToolResult(tool_name="test")
        assert r.trace_id == ""

    def test_output_combines_stdout_stderr(self):
        r = UnifiedToolResult(tool_name="test", stdout="out", stderr="err")
        assert "out" in r.output
        assert "err" in r.output

    def test_output_empty(self):
        r = UnifiedToolResult(tool_name="test")
        assert r.output == ""


class TestLegacyDict:
    def test_to_legacy_dict(self):
        r = UnifiedToolResult(tool_name="nuclei", stdout="output")
        r.status = ToolStatus.SUCCESS
        r.exit_code = 0
        d = r.to_legacy_dict()
        assert d["tool"] == "nuclei"
        assert d["success"] is True
        assert d["stdout"] == "output"

    def test_from_legacy_dict_success(self):
        d = {"tool": "nuclei", "stdout": "ok", "returncode": 0, "success": True, "timeout": False, "duration_ms": 1000}
        r = UnifiedToolResult.from_legacy_dict(d)
        assert r.tool_name == "nuclei"
        assert r.stdout == "ok"
        assert r.status == ToolStatus.SUCCESS
        assert r.duration_seconds == 1.0

    def test_from_legacy_dict_timeout(self):
        d = {"tool": "nuclei", "stdout": "", "returncode": 1, "success": False, "timeout": True, "duration_ms": 5000}
        r = UnifiedToolResult.from_legacy_dict(d)
        assert r.status == ToolStatus.TIMEOUT

    def test_as_dict(self):
        r = UnifiedToolResult(tool_name="test")
        r.status = ToolStatus.SUCCESS
        assert isinstance(r.as_dict(), dict)

    def test_to_finding_list(self):
        r = UnifiedToolResult(tool_name="test")
        r.findings = [{"type": "XSS"}, {"type": "SQLI"}]
        findings = r.to_finding_list()
        assert len(findings) == 2
        assert findings[0]["type"] == "XSS"
