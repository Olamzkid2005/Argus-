"""
MCP Protocol Server - Wraps tool execution with discoverable schemas
Implements Model Context Protocol for standardized tool calling
"""
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ToolSchema:
    """JSON Schema definition for a tool parameter."""
    def __init__(self, name: str, type: str, description: str = "",
                 required: bool = False, enum: list[str] = None,
                 default: Any = None, flag: str = None, **kwargs):
        self.name = name
        self.type = type
        self.description = description
        self.required = required
        self.enum = enum or []
        self.default = default
        self.flag = flag
        # Ignore any extra keys from dict unpacking to avoid TypeError


class ToolDefinition:
    """
    A tool definition loaded from YAML or registered programmatically.
    Mirrors CyberStrikeAI's YAML tool definitions pattern.
    """
    def __init__(self, name: str, command: str, description: str = "",
                 args: list[str] = None, parameters: list[dict] = None,
                 enabled: bool = True, timeout: int = 300,
                 env: dict[str, str] = None):
        self.name = name
        self.command = command
        self.description = description
        self.args = args or []
        self.parameters = [ToolSchema(**p) if isinstance(p, dict) else p for p in (parameters or [])]
        self.enabled = enabled
        self.timeout = timeout
        self.env = env or {}

    def to_dict(self) -> dict:
        """Serialize to MCP tool schema format."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "properties": {
                    p.name: {
                        "type": p.type,
                        "description": p.description,
                        **({"enum": p.enum} if p.enum else {}),
                        **({"default": p.default} if p.default is not None else {}),
                    }
                    for p in self.parameters
                },
                "required": [p.name for p in self.parameters if p.required],
            }
        }


class MCPToolResult:
    """Result of an MCP tool execution."""
    def __init__(self, success: bool, output: str = "", error: str = "",
                 duration_ms: int = 0, tool: str = "", data: dict = None):
        self.success = success
        self.output = output
        self.error = error
        self.duration_ms = duration_ms
        self.tool = tool
        self.data = data or {}

    def to_dict(self) -> dict:
        return {
            "content": [{"type": "text", "text": self.output or self.error}],
            "isError": not self.success,
            "meta": {
                "tool": self.tool,
                "duration_ms": self.duration_ms,
                "success": self.success,
            }
        }


class MCPServer:
    """
    MCP Protocol Server for tool execution.

    Supports:
    - tools/list - discover available tools
    - tools/call - execute a tool by name with parameters
    - Tool registration from YAML definitions
    - Execution tracking and statistics

    This is the foundation for replacing direct subprocess.run() calls
    with a discoverable, schematized protocol layer.
    """

    def __init__(self, tools_dir: str | None = None):
        self._tools: dict[str, ToolDefinition] = {}
        self._execution_stats: dict[str, dict] = {}
        self._tools_dir = tools_dir or os.path.join(
            os.path.dirname(__file__), "tools", "definitions"
        )
        self._load_yaml_tools()

    def _load_yaml_tools(self):
        """Load tool definitions from YAML files in tools/definitions/."""
        tools_path = Path(self._tools_dir)
        if not tools_path.exists():
            tools_path.mkdir(parents=True, exist_ok=True)
            logger.info("Created tools definitions directory: %s", tools_path)
            return

        try:
            import yaml
            for yaml_file in tools_path.glob("*.yaml"):
                try:
                    with open(yaml_file) as f:
                        data = yaml.safe_load(f)
                    if data and "name" in data:
                        tool = ToolDefinition(
                            name=data["name"],
                            command=data.get("command", data["name"]),
                            description=data.get("description", ""),
                            args=data.get("args", []),
                            parameters=data.get("parameters", []),
                            enabled=data.get("enabled", True),
                            timeout=data.get("timeout", 300),
                        )
                        self.register_tool(tool)
                        logger.info("Loaded tool definition: %s", tool.name)
                except Exception as e:
                    logger.warning("Failed to load tool %s: %s", yaml_file, e)
        except ImportError:
            logger.info("PyYAML not installed, skipping YAML tool loading")

    def register_tool(self, tool: ToolDefinition):
        """Register a tool definition."""
        self._tools[tool.name] = tool
        self._execution_stats[tool.name] = {
            "calls": 0, "successes": 0, "failures": 0, "total_duration_ms": 0
        }

    def get_tools(self) -> list[dict]:
        """Get all tool definitions (mcp.tools/list equivalent)."""
        return [t.to_dict() for t in self._tools.values() if t.enabled]

    def get_tool(self, name: str) -> ToolDefinition | None:
        """Get a tool definition by name."""
        return self._tools.get(name)

    def call_tool(self, name: str, arguments: dict = None, timeout: int = None) -> dict:
        """
        Execute a tool by name with arguments (mcp.tools/call equivalent).

        Args:
            name: Tool name
            arguments: Tool parameters (will be mapped to CLI args based on schema)
            timeout: Execution timeout in seconds

        Returns:
            MCP-formatted result dict
        """
        tool = self._tools.get(name)
        if not tool:
            return MCPToolResult(
                success=False, error=f"Unknown tool: {name}", tool=name
            ).to_dict()
        if not tool.enabled:
            return MCPToolResult(
                success=False, error=f"Tool disabled: {name}", tool=name
            ).to_dict()

        # Build command line from tool definition + arguments
        cmd = [tool.command]
        cmd.extend(tool.args)  # Static args

        # Map named arguments to CLI flags
        arguments = arguments or {}
        for param in tool.parameters:
            if param.name in arguments:
                value = arguments[param.name]
                if hasattr(param, 'flag') and param.flag:
                    cmd.append(param.flag)
                    cmd.append(str(value))
                else:
                    cmd.append(str(value))

        # Track execution
        start = time.time()
        self._execution_stats[name]["calls"] += 1

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout or tool.timeout,
            )
            duration_ms = int((time.time() - start) * 1000)

            success = result.returncode == 0
            if success:
                self._execution_stats[name]["successes"] += 1
            else:
                self._execution_stats[name]["failures"] += 1
            self._execution_stats[name]["total_duration_ms"] += duration_ms

            return MCPToolResult(
                success=success,
                output=result.stdout,
                error=result.stderr,
                duration_ms=duration_ms,
                tool=name,
            ).to_dict()

        except subprocess.TimeoutExpired:
            duration_ms = int((time.time() - start) * 1000)
            self._execution_stats[name]["failures"] += 1
            self._execution_stats[name]["total_duration_ms"] += duration_ms
            return MCPToolResult(
                success=False,
                error=f"Tool execution timed out after {timeout or tool.timeout}s",
                duration_ms=duration_ms,
                tool=name,
            ).to_dict()
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            self._execution_stats[name]["failures"] += 1
            return MCPToolResult(
                success=False,
                error=str(e),
                duration_ms=duration_ms,
                tool=name,
            ).to_dict()

    def get_stats(self) -> dict:
        """Get execution statistics for all tools."""
        return dict(self._execution_stats)


# Global MCP server instance
_mcp_server: MCPServer | None = None


def get_mcp_server() -> MCPServer:
    """Get the singleton MCP server instance."""
    global _mcp_server
    if _mcp_server is None:
        _mcp_server = MCPServer()
    return _mcp_server
