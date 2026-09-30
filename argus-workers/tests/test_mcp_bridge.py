"""Tests for tools.mcp_bridge — Category: class"""

import logging

import pytest

from tool_definitions import _PIPELINE_STEP_TOOLS
from tools.mcp_bridge import MCPToolBridge
from tools.tool_runner import ToolRunner


class TestMCPToolBridge:
    """Tests for the MCPToolBridge class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            MCPToolBridge()

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            MCPToolBridge()


class TestMCPToolBridgeRegistration:
    """What the bridge actually exposes over MCP.

    Regression: hand-written registry entries used to replace the generated
    ones wholesale and lose the `binary` their YAML declares, so every
    `python3`-launcher tool was skipped as "binary not found on PATH".
    """

    @pytest.fixture(scope="class")
    def bridge(self):
        return MCPToolBridge(ToolRunner(), engagement_id="test-bridge")

    @pytest.mark.parametrize(
        "name",
        [
            "browser_security_operator",
            "verification_agent",
            "executive_report_generator",
            "finding_correlation_engine",
        ],
    )
    def test_registers_launcher_backed_tools(self, bridge, name):
        from mcp_server import get_mcp_server

        tool = get_mcp_server().get_tool(name)
        assert tool is not None, f"{name} was skipped by the bridge"
        assert tool.command == "python3"

    def test_pipeline_steps_are_exposed_but_never_dispatchable(self, bridge):
        """Registered so the planner can see them; disabled so it cannot run them.

        They used to be absent from the MCP registry entirely, which showed up
        as drift (`missing_from_mcp`) and as "Unknown tool" when a plan named
        one. Being absent also meant the TypeScript planner could not tell
        "this is an in-process step" from "this tool exists but I have not heard
        of it". Listing them with an explicit verdict fixes both.
        """
        from mcp_server import get_mcp_server

        server = get_mcp_server()
        advertised = {t["name"]: t for t in server.get_tools()}
        for name in sorted(_PIPELINE_STEP_TOOLS):
            entry = advertised.get(name)
            assert entry is not None, f"{name} should be advertised"
            assert entry["disabled"] is True, name
            assert entry["pipeline_step"] is True, name
            assert "pipeline step" in entry["disabled_reason"], name

            # ...and calling one gives the reason, not "Unknown tool".
            result = server.call_tool(name, {})
            assert result["isError"] is True, name
            assert "Unknown tool" not in result["content"][0]["text"], name

    def test_missing_binaries_are_reported_but_pipeline_steps_are_not(
        self, monkeypatch, caplog
    ):
        """A pathless registry entry is only a "missing binary" if it names one.

        Pipeline steps cannot be installed, so reporting them next to genuinely
        absent third-party binaries sends the operator chasing impossible fixes.
        """
        monkeypatch.setattr(
            "tools.tool_utils.is_tool_available", lambda *_args, **_kwargs: False
        )

        with caplog.at_level(logging.WARNING, logger="tools.mcp_bridge"):
            MCPToolBridge(ToolRunner(), engagement_id="test-bridge-classify")

        warnings = " ".join(
            r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
        )
        assert "sqlmap" in warnings  # declared for scan, genuinely not installed
        for name in _PIPELINE_STEP_TOOLS:
            assert name not in warnings, (
                f"{name} is a pipeline step, not a missing binary"
            )
