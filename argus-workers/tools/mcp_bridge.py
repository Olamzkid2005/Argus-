"""
MCP Bridge — registers ToolRunner-backed tools with the MCP protocol server.

Derives tool definitions from ``tool_definitions.py`` (the single source of
truth) instead of duplicating metadata inline.  Adding a new tool in
``tool_definitions.py`` automatically makes it available via MCP.
"""

from __future__ import annotations

import logging
import os

from tool_core.result import UnifiedToolResult
from tool_definitions import build_mcp_tool_definitions
from mcp_server import ToolDefinition, get_mcp_server
from tools.tool_runner import ToolRunner
from utils.logging_utils import ScanLogger

logger = logging.getLogger(__name__)


class MCPToolBridge:
    """
    Bridges between the existing ToolRunner and the new MCP protocol.

    Each tool registered in ``tool_definitions.py`` is registered with MCP,
    enabling:
    - Discovery via tools/list
    - Execution via tools/call
    - Streaming output
    - Schema validation

    Unavailable binaries are skipped with a warning.
    """

    def __init__(self, tool_runner: ToolRunner, engagement_id: str = None):
        self.tool_runner = tool_runner
        self.engagement_id = engagement_id
        self.mcp = get_mcp_server()
        self._register_tools()

    def _register_tools(self):
        """Register tools from tool_definitions.py with the MCP server."""
        from tools.tool_utils import is_tool_available

        slog = ScanLogger("mcp_bridge", engagement_id=self.engagement_id)

        # Build MCP ToolDefinition objects from the single source of truth
        mcp_tools = build_mcp_tool_definitions()

        registered_count = 0
        skipped_tools = []

        for tool_def in mcp_tools:
            binary_name = getattr(tool_def, "binary", None) or tool_def.command
            if not is_tool_available(binary_name):
                skipped_tools.append(tool_def.name)
                slog.info(f"Skipping tool '{tool_def.name}' — binary not found on PATH")
                continue
            self.mcp.register_tool(tool_def)
            registered_count += 1

        if skipped_tools:
            logger.warning(
                "Skipped %d unavailable tool(s): %s",
                len(skipped_tools), ", ".join(skipped_tools),
            )
        slog.info(
            "Registered %d tools with MCP (%d skipped)",
            registered_count, len(skipped_tools),
        )

    def call_via_mcp(self, tool: str, arguments: dict = None) -> dict:
        """Call a tool via MCP."""
        slog = ScanLogger("mcp_bridge", engagement_id=self.engagement_id)
        slog.tool_start(f"mcp_call:{tool}")
        result = self.mcp.call_tool(tool, arguments or {})
        slog.tool_complete(f"mcp_call:{tool}")
        return result

    def call_via_runner(self, tool: str, args: list[str], timeout: int = None) -> UnifiedToolResult:
        """Call a tool via the existing ToolRunner."""
        timeout = timeout or 300
        return self.tool_runner.run(tool, args, timeout=timeout)
