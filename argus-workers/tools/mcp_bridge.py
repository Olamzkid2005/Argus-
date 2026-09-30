"""
MCP Bridge — registers ToolRunner-backed tools with the MCP protocol server.

Derives tool definitions from ``tool_definitions.py`` (the single source of
truth) instead of duplicating metadata inline.  Adding a new tool in
``tool_definitions.py`` automatically makes it available via MCP.
"""

from __future__ import annotations

import logging
import os

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

    Two kinds of registry entry are *not* registered, and they are reported
    separately because the fix differs: a tool whose external binary is simply
    not installed (the operator can install it), and an in-process pipeline
    step the orchestrator runs itself (nothing to install, and calling it
    through a PATH-based runner could only fail).
    """

    def __init__(self, tool_runner: ToolRunner, engagement_id: str = None):
        self.tool_runner = tool_runner
        self.engagement_id = engagement_id
        self.mcp = get_mcp_server()
        self._register_tools()

    def _register_tools(self):
        """Register tools from tool_definitions.py with the MCP server."""
        from tool_definitions import is_pipeline_step
        from tools.tool_utils import is_tool_available

        slog = ScanLogger("mcp_bridge", engagement_id=self.engagement_id or "")

        # Build MCP ToolDefinition objects from the single source of truth
        mcp_tools = build_mcp_tool_definitions()

        registered_count = 0
        missing_binaries = []
        pipeline_steps = []

        from tool_definitions import TOOLS as _DECLARED_TOOLS

        unrunnable = []
        for tool_def in mcp_tools:
            # The declarative registry decides first: `phases=[]` means the
            # installed build cannot run the tool at all (dnsx needs a
            # wordlist, gospider segfaults), and a tool reading its API key
            # from the environment is unrunnable while that variable is unset.
            # Registering these anyway re-exposed them to the planner, because
            # MCPToolBridge derived its list from the registry rather than from
            # what the MCP server had already decided.
            declared = _DECLARED_TOOLS.get(tool_def.name)
            if declared is not None and not declared.phases:
                unrunnable.append(tool_def.name)
                slog.info(
                    "Not registering '%s' — no execution phase in "
                    "tool_definitions.TOOLS",
                    tool_def.name,
                )
                continue
            missing_env = [
                var
                for var in getattr(declared, "required_env", ()) or ()
                if not os.environ.get(var)
            ]
            if missing_env:
                unrunnable.append(tool_def.name)
                slog.info(
                    "Not registering '%s' — required environment variable(s) "
                    "not set: %s",
                    tool_def.name,
                    ", ".join(missing_env),
                )
                continue

            binary_name = getattr(tool_def, "binary", None) or tool_def.command
            if is_tool_available(binary_name):
                self.mcp.register_tool(tool_def)
                registered_count += 1
                continue

            # Not on PATH: either an external binary that is not installed, or
            # an in-process step whose name was never a binary to begin with.
            if is_pipeline_step(tool_def.name):
                pipeline_steps.append(tool_def.name)
                slog.info(
                    "Not registering '%s' — in-process pipeline step, not an "
                    "executable",
                    tool_def.name,
                )
                continue

            missing_binaries.append(tool_def.name)
            slog.info("Skipping tool '%s' — binary not found on PATH", tool_def.name)

        if unrunnable:
            logger.info(
                "%d tool(s) not registered — the registry marks them "
                "unrunnable: %s",
                len(unrunnable),
                ", ".join(sorted(unrunnable)),
            )

        if missing_binaries:
            logger.warning(
                "Skipped %d tool(s) whose external binary is not on PATH: %s",
                len(missing_binaries),
                ", ".join(missing_binaries),
            )
        if pipeline_steps:
            logger.info(
                "%d in-process pipeline step(s) are not exposed over MCP: %s",
                len(pipeline_steps),
                ", ".join(pipeline_steps),
            )
        slog.info(
            "Registered %d tools with MCP (%d skipped: %d missing binary, "
            "%d pipeline step)",
            registered_count,
            len(missing_binaries) + len(pipeline_steps),
            len(missing_binaries),
            len(pipeline_steps),
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
