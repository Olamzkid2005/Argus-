"""Tests for mcp_server.py — MCPServer, ToolSchema, ToolDefinition, MCPToolResult."""

import tempfile
from pathlib import Path

from mcp_server import (
    MCPServer,
    MCPToolResult,
    ToolDefinition,
    ToolSchema,
    get_mcp_server,
)


class TestToolSchema:
    def test_minimal(self):
        ts = ToolSchema(name="target", type="string")
        assert ts.name == "target"
        assert ts.type == "string"
        assert ts.description == ""
        assert ts.required is False
        assert ts.enum == []
        assert ts.default is None
        assert ts.flag is None

    def test_full(self):
        ts = ToolSchema(
            name="target", type="string", description="The target",
            required=True, enum=["a", "b"], default="x", flag="-u",
        )
        assert ts.required is True
        assert ts.enum == ["a", "b"]
        assert ts.default == "x"
        assert ts.flag == "-u"

    def test_extra_kwargs_ignored(self):
        """Extra kwargs from dict unpacking should not cause TypeError."""
        ts = ToolSchema(name="x", type="string", extra_field="ignored")
        assert ts.name == "x"


class TestToolDefinition:
    def test_minimal(self):
        td = ToolDefinition(name="nuclei", command="nuclei")
        assert td.name == "nuclei"
        assert td.command == "nuclei"
        assert td.enabled is True
        assert td.timeout == 300

    def test_parameters_from_dict(self):
        td = ToolDefinition(
            name="test", command="test",
            parameters=[{"name": "target", "type": "string", "required": True}],
        )
        assert len(td.parameters) == 1
        assert td.parameters[0].name == "target"
        assert td.parameters[0].required is True

    def test_to_dict(self):
        td = ToolDefinition(
            name="nmap", command="nmap",
            description="Port scanner",
        )
        d = td.to_dict()
        assert d["name"] == "nmap"
        assert d["description"] == "Port scanner"
        assert "inputSchema" in d

    def test_to_dict_with_params(self):
        td = ToolDefinition(
            name="nuclei", command="nuclei",
            parameters=[{"name": "target", "type": "string", "required": True}],
        )
        d = td.to_dict()
        assert d["inputSchema"]["required"] == ["target"]
        assert "target" in d["inputSchema"]["properties"]


class TestMCPToolResult:
    def test_success_default(self):
        r = MCPToolResult(success=True, output="ok", tool="nuclei")
        d = r.to_dict()
        assert d["isError"] is False
        assert d["content"][0]["text"] == "ok"
        assert d["meta"]["tool"] == "nuclei"
        assert d["meta"]["success"] is True

    def test_error(self):
        r = MCPToolResult(success=False, error="failed", tool="test")
        d = r.to_dict()
        assert d["isError"] is True
        assert d["content"][0]["text"] == "failed"


class TestMCPServer:
    def test_init(self):
        server = MCPServer()
        assert server._tools == {}
        assert server._execution_stats == {}

    def test_register_tool(self):
        server = MCPServer()
        td = ToolDefinition(name="test", command="test")
        server.register_tool(td)
        assert "test" in server._tools
        assert server._execution_stats["test"]["calls"] == 0

    def test_get_tools_returns_enabled(self):
        server = MCPServer()
        server.register_tool(ToolDefinition(name="enabled", command="e", enabled=True))
        server.register_tool(ToolDefinition(name="disabled", command="d", enabled=False))
        tools = server.get_tools()
        names = [t["name"] for t in tools]
        assert "enabled" in names
        assert "disabled" not in names

    def test_get_tool_returns_none_for_missing(self):
        server = MCPServer()
        assert server.get_tool("nonexistent") is None

    def test_call_unknown_tool(self):
        server = MCPServer()
        result = server.call_tool("unknown")
        assert result["isError"] is True
        assert "Unknown tool" in result["content"][0]["text"]

    def test_call_disabled_tool(self):
        server = MCPServer()
        server.register_tool(ToolDefinition(name="off", command="off", enabled=False))
        result = server.call_tool("off")
        assert result["isError"] is True
        assert "disabled" in result["content"][0]["text"]

    def test_call_tool_args_sanitized(self):
        """Shell injection chars in args should be rejected."""
        server = MCPServer()
        td = ToolDefinition(
            name="test", command="echo",
            parameters=[{"name": "target", "type": "string", "flag": "-n"}],
        )
        server.register_tool(td)
        result = server.call_tool("test", {"target": "hello; rm -rf /"})
        assert result["isError"] is True
        assert "Security validation" in result["content"][0]["text"]

    def test_call_tool_injection_detection(self):
        """Backtick injection should be rejected."""
        server = MCPServer()
        td = ToolDefinition(
            name="test", command="echo",
            parameters=[{"name": "msg", "type": "string", "flag": "-n"}],
        )
        server.register_tool(td)
        result = server.call_tool("test", {"msg": "`cat /etc/passwd`"})
        assert result["isError"] is True
        assert "shell metacharacters" in result["content"][0]["text"].lower()

    def test_get_stats(self):
        server = MCPServer()
        td = ToolDefinition(name="test", command="test")
        server.register_tool(td)
        stats = server.get_stats()
        assert "test" in stats
        assert stats["test"]["calls"] == 0

    def test_yaml_loading_nonexistent_dir(self):
        """Server should handle missing tools directory gracefully."""
        with tempfile.TemporaryDirectory() as tmp:
            server = MCPServer(tools_dir=str(Path(tmp) / "nonexistent"))
            assert server._tools == {}


class TestGetMCPServer:
    def test_singleton(self):
        s1 = get_mcp_server()
        s2 = get_mcp_server()
        assert s1 is s2
