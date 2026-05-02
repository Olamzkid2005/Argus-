"""
Tool Registry - Registry of available tools for the agent to use.
Bridges to the MCP protocol server for tool discovery.
"""
import logging
import time
from collections.abc import Callable

from .agent_result import AgentResult

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Registry of available tools for the agent to use."""

    def __init__(self):
        self._tools: dict[str, Callable] = {}
        self._tool_metadata: dict[str, dict] = {}

    def register(self, name: str, func: Callable, metadata: dict = None):
        """Register a callable tool function."""
        self._tools[name] = func
        self._tool_metadata[name] = metadata or {
            "name": name,
            "description": "",
            "parameters": [],
        }

    def get_tool(self, name: str) -> Callable | None:
        """Get a tool function by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[dict]:
        """List all available tools with their metadata."""
        return list(self._tool_metadata.values())

    def call(self, name: str, **kwargs) -> AgentResult:
        """Call a tool function by name with arguments."""
        start = time.time()
        func = self._tools.get(name)
        if not func:
            return AgentResult(
                tool=name, success=False,
                error=f"Unknown tool: {name}"
            )
        try:
            result = func(**kwargs)
            duration = int((time.time() - start) * 1000)
            if isinstance(result, AgentResult):
                result.duration_ms = duration
                return result
            return AgentResult(
                tool=name, success=True,
                output=str(result), duration_ms=duration
            )
        except Exception as e:
            duration = int((time.time() - start) * 1000)
            return AgentResult(
                tool=name, success=False,
                error=str(e), duration_ms=duration
            )
