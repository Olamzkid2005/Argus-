"""
MCP Bridge — registers ToolRunner-backed tools with the MCP protocol server.

Derives tool definitions from ``tool_definitions.py`` (the single source of
truth) instead of duplicating metadata inline.  Adding a new tool in
``tool_definitions.py`` automatically makes it available via MCP.
"""

from __future__ import annotations

import logging

from mcp_server import get_mcp_server
from tool_core.result import UnifiedToolResult
from tool_definitions import build_mcp_tool_definitions
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

        slog = ScanLogger("mcp_bridge", engagement_id=self.engagement_id or "")

        # Build MCP ToolDefinition objects from the single source of truth
        mcp_tools = build_mcp_tool_definitions()

        registered_count = 0
        skipped_tools = []

        for tool_def in mcp_tools:
            binary_name = getattr(tool_def, "binary", None) or tool_def.command
            if not is_tool_available(binary_name):
                skipped_tools.append(tool_def.name)
                slog.info(
                    "Skipping tool '%s' — binary not found on PATH", tool_def.name
                )
                continue
            self.mcp.register_tool(tool_def)
            registered_count += 1

        if skipped_tools:
            logger.warning(
                "Skipped %d unavailable tool(s): %s",
                len(skipped_tools),
                ", ".join(skipped_tools),
            )
        slog.info(
            "Registered %d tools with MCP (%d skipped)",
            registered_count,
            len(skipped_tools),
        )

    def call_via_mcp(
        self, tool: str, arguments: dict = None, cache_mode: str | None = None
    ) -> dict:
        """Call a tool via MCP with scope validation and cache control.

        Gap 4.4: cache_mode is forwarded to call_tool() to control
        whether tool outputs are cached/retrieved from cache.

        When ``engagement_id`` is set, this method creates a
        ``ScopeValidator`` and passes it to ``call_tool`` so the
        target is validated against the engagement's authorized scope
        before the tool subprocess is launched.

        Args:
            tool: Tool name
            arguments: Tool parameters
            cache_mode: Cache execution mode ("normal", "no_cache", "refresh")

        Returns:
            MCP-formatted result dict
        """
        scope_validator = None
        if self.engagement_id:
            try:
                from orchestrator_pkg.engagement import EngagementService
                from tools.scope_validator import ScopeValidator

                authorized_scope = EngagementService.load_authorized_scope(
                    self.engagement_id
                )
                if authorized_scope:
                    scope_validator = ScopeValidator(
                        self.engagement_id, authorized_scope
                    )
            except Exception as e:
                logger.warning(
                    "Could not create scope validator for engagement %s: %s",
                    self.engagement_id,
                    e,
                )

        slog = ScanLogger("mcp_bridge", engagement_id=self.engagement_id or "")
        slog.tool_start(f"mcp_call:{tool}")
        result = self.mcp.call_tool(
            tool,
            arguments or {},
            cache_mode=cache_mode,
            engagement_id=self.engagement_id,
            scope_validator=scope_validator,
        )
        slog.tool_complete(f"mcp_call:{tool}")
        return result

    def call_via_runner(
        self,
        tool: str,
        args: list[str],
        timeout: int = None,
        cache_mode: str | None = None,
    ) -> UnifiedToolResult:
        """Call a tool via the existing ToolRunner.

        Gap 4.4: cache_mode is forwarded to tool_runner.run() to control
        whether tool outputs are cached/retrieved from cache.

        Args:
            tool: Tool name
            args: CLI arguments
            timeout: Execution timeout in seconds
            cache_mode: Cache execution mode ("normal", "no_cache", "refresh")

        Returns:
            UnifiedToolResult
        """
        timeout = timeout or 300
        from cache import CacheMode
        _cm = CacheMode(cache_mode) if cache_mode else CacheMode.NORMAL
        return self.tool_runner.run(tool, args, timeout=timeout, cache_mode=_cm)
