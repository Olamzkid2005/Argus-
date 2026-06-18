"""
Regression tests for advanced security tools.

Tests verify that existing functionality is not broken by the new tools
and that the new tools don't interfere with the existing tool system.
"""

from unittest.mock import MagicMock

from tool_core.base import ToolContext
from tool_core.result import ToolStatus, UnifiedToolResult


class TestExistingToolUnaffected:
    """Verify existing tools still work correctly after adding new tools."""

    def test_nuclei_still_registered(self):
        from tool_definitions import TOOLS

        assert "nuclei" in TOOLS
        assert TOOLS["nuclei"].phases == ["scan", "deep_scan"]

    def test_httpx_still_registered(self):
        from tool_definitions import TOOLS

        assert "httpx" in TOOLS

    def test_subfinder_still_registered(self):
        from tool_definitions import TOOLS

        assert "subfinder" in TOOLS

    def test_original_tools_count(self):
        from tool_definitions import TOOLS

        assert len(TOOLS) >= 46


class TestToolContextUnaffected:
    """Verify ToolContext still works correctly."""

    def test_tool_context_creation(self):
        ctx = ToolContext(target="https://example.com", engagement_id="test")
        assert ctx.target == "https://example.com"
        assert ctx.engagement_id == "test"

    def test_tool_context_defaults(self):
        ctx = ToolContext()
        assert ctx.target == ""
        assert ctx.timeout == 120


class TestUnifiedToolResultUnaffected:
    """Verify UnifiedToolResult still works correctly."""

    def test_success_result(self):
        result = UnifiedToolResult(tool_name="test")
        result.status = ToolStatus.SUCCESS
        result.mark_finished()
        assert result.success
        assert result.duration_seconds >= 0

    def test_legacy_dict(self):
        result = UnifiedToolResult(tool_name="test", stdout="output")
        result.status = ToolStatus.SUCCESS
        result.mark_finished()
        d = result.to_legacy_dict()
        assert d["tool"] == "test"
        assert d["success"] is True


class TestMCPBridgeUnaffected:
    """Verify MCP bridge still works with new tools registered."""

    def test_build_mcp_definitions(self):
        from tool_definitions import build_mcp_tool_definitions

        mcp_tools = build_mcp_tool_definitions()
        assert len(mcp_tools) > 0

    def test_new_tools_in_mcp_definitions(self):
        from tool_definitions import build_mcp_tool_definitions

        mcp_tools = build_mcp_tool_definitions()
        tool_names = [t.name for t in mcp_tools]
        assert "finding_correlation_engine" in tool_names
        assert "attack_path_generator" in tool_names


class TestAgentInternalToolsUnaffected:
    """Verify agent-internal tools still work."""

    def test_register_login_still_internal(self):
        from tool_definitions import _AGENT_INTERNAL_TOOLS

        assert "register" in _AGENT_INTERNAL_TOOLS
        assert "login" in _AGENT_INTERNAL_TOOLS


class TestPhaseToolsUnaffected:
    """Verify phase tool assignments still work."""

    def test_recon_phase_has_tools(self):
        from tool_definitions import get_tools_for_phase

        tools = get_tools_for_phase("recon")
        assert len(tools) > 0

    def test_scan_phase_has_tools(self):
        from tool_definitions import get_tools_for_phase

        tools = get_tools_for_phase("scan")
        assert len(tools) > 0

    def test_analyze_phase_includes_new_tools(self):
        from tool_definitions import get_tools_for_phase

        tools = get_tools_for_phase("analyze")
        tool_names = [t.name for t in tools]
        assert "finding_correlation_engine" in tool_names

    def test_report_phase_includes_new_tools(self):
        from tool_definitions import get_tools_for_phase

        tools = get_tools_for_phase("report")
        tool_names = [t.name for t in tools]
        assert "executive_report_generator" in tool_names


class TestEvaluateGateUnaffected:
    """Verify gate evaluation still works."""

    def test_no_gate_always_runs(self):
        from tool_definitions import evaluate_gate

        ctx = MagicMock()
        assert evaluate_gate("nuclei", ctx) is True

    def test_gating_still_works(self):
        from tool_definitions import evaluate_gate

        ctx = MagicMock()
        ctx.tech_stack = ["python"]
        ctx.target_url = "https://example.com"
        assert evaluate_gate("bandit", ctx) is True


class TestToolRunnerUnaffected:
    """Verify ToolRunner is not broken by new registrations."""

    def test_tool_runner_imports(self):
        from tools.tool_runner import ToolRunner

        assert ToolRunner is not None

    def test_dangerous_patterns_unchanged(self):
        from tools.tool_runner import ToolRunner

        assert "rm -rf" in ToolRunner.DANGEROUS_PATTERNS
        assert "DROP TABLE" in ToolRunner.DANGEROUS_PATTERNS


class TestAsyncToolRunnerUnaffected:
    """Verify AsyncToolRunner is not broken."""

    def test_async_tool_runner_imports(self):
        from tool_core.sandbox import AsyncToolRunner

        assert AsyncToolRunner is not None

    def test_findings_exit_codes_unchanged(self):
        from tool_core.sandbox import AsyncToolRunner

        assert "semgrep" in AsyncToolRunner.FINDINGS_EXIT_CODES
        assert 1 in AsyncToolRunner.FINDINGS_EXIT_CODES["semgrep"]


class TestReActAgentUnaffected:
    """Verify ReActAgent phase tools are loaded correctly."""

    def test_phase_tools_loaded(self):
        from agent.react_agent import ReActAgent

        ReActAgent._ensure_phase_tools()
        assert "recon" in ReActAgent.PHASE_TOOLS
        assert "scan" in ReActAgent.PHASE_TOOLS
