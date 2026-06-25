"""Integration tests for MCP server JSON-RPC round trip through stdin/stdout.

These tests spawn a real Python MCP server subprocess and send real
JSON-RPC messages over stdin/stdout, exercising the full transport
pipeline that production code uses.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Path to the test helper MCP server
_HELPERS_DIR = Path(__file__).resolve().parent / "helpers"
_TEST_SERVER = str(_HELPERS_DIR / "test_helper_mcp_server.py")
# Path to the real mcp_server.py for testing actual tool dispatch
_MCP_SERVER = str(Path(__file__).resolve().parent.parent / "mcp_server.py")


def _read_response(proc: subprocess.Popen, timeout: float = 5.0) -> dict:
    """Read a single JSON-RPC response line from stdout with timeout."""
    import select

    deadline = time.time() + timeout
    while time.time() < deadline:
        r, _w, _e = select.select([proc.stdout], [], [], 0.1)
        if r:
            line = proc.stdout.readline()
            if line:
                return json.loads(line.strip())
    raise TimeoutError(f"No response received within {timeout}s")


def _send_request(proc: subprocess.Popen, request: dict) -> None:
    """Send a JSON-RPC request to the server's stdin."""
    proc.stdin.write(json.dumps(request) + "\n")
    proc.stdin.flush()


@pytest.fixture
def test_server():
    """Fixture that starts the test MCP server and cleans up on teardown."""
    proc = subprocess.Popen(
        [sys.executable, _TEST_SERVER],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


class TestCallToolRoundTrip:
    """Full JSON-RPC round trip through the test MCP server."""

    def test_ping(self, test_server):
        """Ping request returns pong."""
        _send_request(test_server, {
            "jsonrpc": "2.0", "id": "1", "method": "ping",
        })
        resp = _read_response(test_server)
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == "1"
        assert resp["result"] == "pong"

    def test_list_tools(self, test_server):
        """list_tools returns a tool list with echo."""
        _send_request(test_server, {
            "jsonrpc": "2.0", "id": "1", "method": "list_tools",
        })
        resp = _read_response(test_server)
        assert resp["id"] == "1"
        tools = resp["result"]["tools"]
        names = [t["name"] for t in tools]
        assert "echo" in names

    def test_call_tool_echo_happy_path(self, test_server):
        """Call echo tool with a message and get it back."""
        _send_request(test_server, {
            "jsonrpc": "2.0",
            "id": "2",
            "method": "call_tool",
            "params": {
                "name": "echo",
                "arguments": {"message": "hello world"},
            },
        })
        resp = _read_response(test_server)
        assert resp["id"] == "2"
        result = resp["result"]
        assert result["meta"]["success"] is True
        assert result["meta"]["tool"] == "echo"
        assert result["content"][0]["text"] == "hello world"
        assert result["isError"] is False

    def test_call_tool_unknown_tool(self, test_server):
        """Call_tool for a nonexistent tool returns an error."""
        _send_request(test_server, {
            "jsonrpc": "2.0",
            "id": "3",
            "method": "call_tool",
            "params": {
                "name": "nonexistent_tool_xyz",
                "arguments": {},
            },
        })
        resp = _read_response(test_server)
        assert resp["id"] == "3"
        result = resp["result"]
        assert result["isError"] is True
        assert result["meta"]["success"] is False
        assert "Unknown tool" in result["content"][0]["text"]

    def test_call_tool_with_special_characters(self, test_server):
        """Message with special characters is echoed back correctly."""
        special_msg = "hello & goodbye <script>alert('xss')</script>"
        _send_request(test_server, {
            "jsonrpc": "2.0",
            "id": "4",
            "method": "call_tool",
            "params": {
                "name": "echo",
                "arguments": {"message": special_msg},
            },
        })
        resp = _read_response(test_server)
        result = resp["result"]
        assert result["content"][0]["text"] == special_msg
        assert result["meta"]["success"] is True

    def test_call_tool_empty_message(self, test_server):
        """Empty message is echoed back as empty string."""
        _send_request(test_server, {
            "jsonrpc": "2.0",
            "id": "5",
            "method": "call_tool",
            "params": {
                "name": "echo",
                "arguments": {"message": ""},
            },
        })
        resp = _read_response(test_server)
        result = resp["result"]
        assert result["content"][0]["text"] == ""
        assert result["meta"]["success"] is True


class TestRealMCPServerCallTool:
    """Integration tests using the real mcp_server.py with known tools."""

    def test_call_tool_unknown_tool_on_real_server(self):
        """Real MCP server returns error for unknown tool."""
        proc = subprocess.Popen(
            [sys.executable, _MCP_SERVER],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        try:
            _send_request(proc, {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "call_tool",
                "params": {
                    "name": "definitely_not_a_real_tool_xyz_123",
                    "arguments": {},
                },
            })
            resp = _read_response(proc)
            assert resp["id"] == "1"
            result = resp["result"]
            assert result["isError"] is True
            assert "Unknown tool" in result["content"][0]["text"]
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    def test_list_tools_on_real_server_returns_tools(self):
        """Real MCP server returns a non-empty tool list."""
        proc = subprocess.Popen(
            [sys.executable, _MCP_SERVER],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        try:
            _send_request(proc, {
                "jsonrpc": "2.0", "id": "1", "method": "list_tools",
            })
            resp = _read_response(proc)
            assert resp["id"] == "1"
            tools = resp["result"]["tools"]
            assert isinstance(tools, list)
            assert len(tools) > 0
            # Should have some real tools
            names = [t["name"] for t in tools]
            assert "nuclei" in names or "nmap" in names or "echo" in names
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


class TestJSONRPCErrorHandling:
    """Error handling at the JSON-RPC transport layer."""

    def test_invalid_json(self, test_server):
        """Invalid JSON input returns a parse error."""
        test_server.stdin.write("not valid json\n")
        test_server.stdin.flush()
        resp = _read_response(test_server)
        assert "error" in resp
        assert resp["error"]["code"] == -32700

    def test_malformed_json_between_valid_requests(self, test_server):
        """Malformed JSON between valid requests doesn't break the server."""
        # Send valid request
        _send_request(test_server, {
            "jsonrpc": "2.0", "id": "1", "method": "ping",
        })
        resp1 = _read_response(test_server)
        assert resp1["result"] == "pong"

        # Send garbage
        test_server.stdin.write("{{{garbage}}}\n")
        test_server.stdin.flush()
        resp2 = _read_response(test_server)
        assert "error" in resp2
        assert resp2["error"]["code"] == -32700

        # Send another valid request — server should still work
        _send_request(test_server, {
            "jsonrpc": "2.0", "id": "2", "method": "ping",
        })
        resp3 = _read_response(test_server)
        assert resp3["result"] == "pong"
        assert resp3["id"] == "2"

    def test_unknown_method(self, test_server):
        """Unknown method returns method not found error."""
        _send_request(test_server, {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "nonexistent_method_xyz",
        })
        resp = _read_response(test_server)
        assert resp["id"] == "1"
        assert resp["error"]["code"] == -32601
        assert "Method not found" in resp["error"]["message"]
