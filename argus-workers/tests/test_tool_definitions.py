"""Tests for tool_definitions.py — TOOLS registry, helpers, and gate evaluation."""

from unittest.mock import patch

import pytest

from tool_definitions import (
    ALL_PHASES,
    TOOLS,
    SignalQuality,
    ToolDefinition,
    ToolParameter,
    ToolRequires,
    build_mcp_tool_definitions,
    build_phase_tools_dict,
    evaluate_gate,
    get_phase_tool_names,
    get_tool,
    get_tools_for_phase,
    is_tool_available,
)


class TestSignalQuality:
    def test_values(self):
        assert SignalQuality.CONFIRMED.value == "confirmed"
        assert SignalQuality.PROBABLE.value == "probable"
        assert SignalQuality.CANDIDATE.value == "candidate"


class TestToolRequires:
    def test_defaults(self):
        req = ToolRequires()
        assert req.tech_contains == []
        assert req.recon_signals == []
        assert req.target_scheme is None

    def test_full(self):
        req = ToolRequires(tech_contains=["python"], recon_signals=["has_api"], target_scheme="https")
        assert req.tech_contains == ["python"]
        assert req.recon_signals == ["has_api"]
        assert req.target_scheme == "https"


class TestToolParameter:
    def test_defaults(self):
        p = ToolParameter(name="target", description="Target URL")
        assert p.name == "target"
        assert p.required is False
        assert p.flag is None
        assert p.default is None
        assert p.enum is None


class TestToolDefinition:
    def test_minimal(self):
        td = ToolDefinition(name="test", description="A test tool")
        assert td.name == "test"
        assert td.description == "A test tool"
        assert td.phases == []
        assert td.timeout == 300
        assert td.parallel_safe is True
        assert td.signal_quality == SignalQuality.CANDIDATE

    def test_frozen(self):
        td = ToolDefinition(name="test", description="test")
        with pytest.raises(AttributeError):
            td.name = "new-name"  # frozen dataclass


class TestTOOLSRegistry:
    def test_nuclei_registered(self):
        assert "nuclei" in TOOLS
        assert TOOLS["nuclei"].description != ""
        assert "scan" in TOOLS["nuclei"].phases

    def test_httpx_registered(self):
        assert "httpx" in TOOLS
        assert "recon" in TOOLS["httpx"].phases

    def test_all_phases_covered(self):
        """Every phase should have at least one tool registered."""
        tools_by_phase = {}
        for name, td in TOOLS.items():
            for phase in td.phases:
                tools_by_phase.setdefault(phase, []).append(name)
        for phase in ALL_PHASES:
            assert phase in tools_by_phase, f"Phase {phase} has no tools"

    def test_tool_names_unique(self):
        assert len(TOOLS) == len({t.name for t in TOOLS.values()})

    def test_metadata_on_nuclei(self):
        td = TOOLS["nuclei"]
        assert td.metadata is not None
        assert td.metadata.vendor == "projectdiscovery"
        assert td.metadata.homepage is not None


class TestGetTool:
    def test_returns_none_for_missing(self):
        assert get_tool("nonexistent_tool_xyz") is None

    def test_returns_tool(self):
        td = get_tool("nuclei")
        assert td is not None
        assert td.name == "nuclei"


class TestIsToolAvailable:
    def test_agent_internal_always_available(self):
        """register and login are agent-internal tools."""
        assert is_tool_available("register") is True
        assert is_tool_available("login") is True

    def test_unknown_tool_not_available(self):
        assert is_tool_available("__nonexistent_binary_xyz__") is False


class TestGetToolsForPhase:
    def test_recon_returns_tools(self):
        with patch("tool_definitions.is_tool_available", return_value=True):
            tools = get_tools_for_phase("recon")
            assert len(tools) > 0
            names = [t.name for t in tools]
            assert "httpx" in names

    def test_report_returns_tools(self):
        with patch("tool_definitions.is_tool_available", return_value=True):
            tools = get_tools_for_phase("report")
            assert len(tools) > 0
            names = [t.name for t in tools]
            assert "report-generator" in names

    def test_phase_empty_not_in_error(self):
        """nmap has empty phases and should not appear in any phase."""
        with patch("tool_definitions.is_tool_available", return_value=True):
            tools = []
            for phase in ALL_PHASES:
                tools.extend(get_tools_for_phase(phase))
            assert "nmap" not in [t.name for t in tools]


class TestGetPhaseToolNames:
    def test_recon(self):
        with patch("tool_definitions.is_tool_available", return_value=True):
            names = get_phase_tool_names("recon")
            assert isinstance(names, list)
            assert len(names) > 0

    def test_scan(self):
        with patch("tool_definitions.is_tool_available", return_value=True):
            names = get_phase_tool_names("scan")
            assert isinstance(names, list)
            assert "nuclei" in names


class TestBuildPhaseToolsDict:
    def test_has_all_phases(self):
        with patch("tool_definitions.is_tool_available", return_value=True):
            d = build_phase_tools_dict()
            for phase in ALL_PHASES:
                assert phase in d, f"Missing phase: {phase}"
                assert isinstance(d[phase], list)

    def test_recon_nonempty(self):
        with patch("tool_definitions.is_tool_available", return_value=True):
            d = build_phase_tools_dict()
            assert len(d["recon"]) > 0


class TestEvaluateGate:
    def test_no_requires_always_true(self):
        """Tools with no requires gate should always run."""
        assert evaluate_gate("nuclei", None) is True

    def test_no_tool_definition_returns_true(self):
        assert evaluate_gate("nonexistent", None) is True

    def test_tech_contains_matches(self):
        class MockReconContext:
            tech_stack = ["python", "django"]
            target_url = "https://example.com"
            has_api = True

        assert evaluate_gate("bandit", MockReconContext()) is True

    def test_tech_contains_no_match(self):
        class MockReconContext:
            tech_stack = ["javascript", "node"]
            target_url = "https://example.com"
            has_api = True

        assert evaluate_gate("bandit", MockReconContext()) is False

    def test_target_scheme_matches(self):
        class MockReconContext:
            target_url = "https://example.com"
            tech_stack = []
            has_api = True

        assert evaluate_gate("testssl", MockReconContext()) is True

    def test_target_scheme_no_match(self):
        class MockReconContext:
            target_url = "http://example.com"
            tech_stack = []
            has_api = True

        assert evaluate_gate("testssl", MockReconContext()) is False

    def test_recon_signals_all_true(self):
        class MockReconContext:
            has_api = True
            has_login_page = True
            tech_stack = []

        assert evaluate_gate("jwt_tool", MockReconContext()) is True

    def test_recon_signals_one_false(self):
        class MockReconContext:
            has_api = False
            has_login_page = True
            tech_stack = []

        assert evaluate_gate("jwt_tool", MockReconContext()) is False


class TestBuildMCPToolDefinitions:
    def test_returns_list(self):
        mcp_tools = build_mcp_tool_definitions()
        assert isinstance(mcp_tools, list)
        assert len(mcp_tools) > 0

    def test_has_nuclei(self):
        mcp_tools = build_mcp_tool_definitions()
        names = [t.name for t in mcp_tools]
        assert "nuclei" in names
