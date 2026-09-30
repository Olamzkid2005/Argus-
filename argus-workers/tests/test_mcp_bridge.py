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

    def test_pipeline_steps_are_never_exposed(self, bridge):
        from mcp_server import get_mcp_server

        server = get_mcp_server()
        for name in sorted(_PIPELINE_STEP_TOOLS):
            assert server.get_tool(name) is None, (
                f"{name} is an in-process pipeline step and must not be "
                f"advertised as an MCP tool"
            )

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
