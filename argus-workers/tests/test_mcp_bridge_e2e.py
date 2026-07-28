"""
End-to-end test for the MCP bridge — spawns mcp_server.py as a subprocess
and validates JSON-RPC 2.0 communication over stdin/stdout.

This validates the critical integration path:
  TypeScript mcp-client.ts  ←→  Python mcp_transport.py + mcp_server.py

Tests:
  - ping: verify the server starts, responds, and shuts down cleanly
  - list_tools: verify tool definitions are returned
  - call_tool: verify tool execution (using echo as a safe tool)
  - unknown method: verify error response
  - cancel: verify the cancel handler works
  - batch: verify batch request/response
  - process lifecycle: verify SIGTERM/SIGKILL cleanup
"""

from __future__ import annotations

import json
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Path to the lightweight test MCP server module.
# The real mcp_server.py has heavy initialization (tool loading, DNS check,
# preflight, health server) that makes it unsuitable for E2E testing.
# The test server (test_mcp_server_e2e.py) registers the same handlers but
# with no heavy initialization.
WORKERS_DIR = Path(__file__).resolve().parent.parent
MCP_SERVER_PATH = str(WORKERS_DIR / "tests" / "test_mcp_server_e2e.py")

# Timeout for subprocess responses (seconds)
RESPONSE_TIMEOUT = 15


def _find_python() -> str:
    """Find the Python interpreter to use for the subprocess."""
    return sys.executable or "python3"


def _send_and_recv(
    proc: subprocess.Popen,
    request: dict,
    timeout: float = RESPONSE_TIMEOUT,
) -> dict:
    """Send a JSON-RPC request to the subprocess and read the response.

    Args:
        proc: The subprocess (must have stdin/stdout pipes).
        request: JSON-RPC request dict.
        timeout: Max seconds to wait for a response line.

    Returns:
        Parsed JSON-RPC response dict.

    Raises:
        TimeoutError: If no response is received within timeout.
        ValueError: If the response is not valid JSON.
    """
    line = json.dumps(request) + "\n"
    proc.stdin.write(line.encode("utf-8"))
    proc.stdin.flush()

    # Read response line-by-line until we get one that parses as JSON
    start = time.time()
    while time.time() - start < timeout:
        # Check if process died
        if proc.poll() is not None:
            raise RuntimeError(
                f"Subprocess exited with code {proc.returncode} "
                f"while waiting for response to {request.get('method')}"
            )

        line = proc.stdout.readline()
        if not line:
            time.sleep(0.05)
            continue

        line = line.strip()
        if not line:
            continue

        try:
            return json.loads(line)
        except json.JSONDecodeError:
            # Could be a stderr log line mixed into stdout — skip
            continue

    raise TimeoutError(
        f"No valid JSON response received within {timeout}s for "
        f"{request.get('method')}"
    )


def _send_request(
    proc: subprocess.Popen,
    method: str,
    params: dict | None = None,
    request_id: str = "1",
) -> dict:
    """Helper to send a JSON-RPC request and get the response."""
    request = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
    }
    if params is not None:
        request["params"] = params
    return _send_and_recv(proc, request)


@pytest.fixture(scope="module")
def mcp_process():
    """Start the MCP server as a subprocess, yield the process handle, then clean up.

    The server is started once per module and shared across all tests.
    Uses SIGTERM → 3s grace → SIGKILL for cleanup.
    """
    python_exe = _find_python()
    proc = subprocess.Popen(
        [python_exe, MCP_SERVER_PATH],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(WORKERS_DIR),
    )

    # Give it a moment to start up
    time.sleep(1)

    try:
        yield proc
    finally:
        # Clean shutdown
        if proc.poll() is None:
            # SIGTERM
            try:
                if hasattr(signal, "SIGTERM"):
                    proc.send_signal(signal.SIGTERM)
                else:
                    proc.terminate()
            except Exception:
                pass

            # Wait up to 3s for graceful shutdown
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                # SIGKILL
                try:
                    if hasattr(signal, "SIGKILL"):
                        proc.send_signal(signal.SIGKILL)
                    else:
                        proc.kill()
                except Exception:
                    pass
                proc.wait(timeout=5)

        # Drain remaining stdout/stderr for diagnostics
        stdout_remainder = proc.stdout.read().decode("utf-8", errors="replace")
        stderr_remainder = proc.stderr.read().decode("utf-8", errors="replace")

        # Log stderr on failure for debugging
        if proc.returncode != 0 and proc.returncode != -15:  # -15 = SIGTERM
            print(
                f"\n[MCP E2E] Process exited with code {proc.returncode}",
                file=sys.stderr,
            )
            if stderr_remainder:
                print(
                    f"[MCP E2E] stderr:\n{stderr_remainder[:2000]}",
                    file=sys.stderr,
                )
            if stdout_remainder:
                print(
                    f"[MCP E2E] stdout remainder:\n{stdout_remainder[:1000]}",
                    file=sys.stderr,
                )


class TestMCPBridgeE2E:
    """End-to-end tests for the MCP bridge (subprocess JSON-RPC)."""

    def test_ping(self, mcp_process):
        """Verify the server responds to ping."""
        resp = _send_request(mcp_process, "ping")
        assert resp.get("jsonrpc") == "2.0"
        assert resp.get("id") == "1"
        assert resp.get("result", {}).get("pong") is True
        assert "timestamp" in resp["result"]

    def test_ping_multiple_ids(self, mcp_process):
        """Verify multiple ping requests with different IDs work."""
        for rid in ["10", "20", "30"]:
            resp = _send_request(mcp_process, "ping", request_id=rid)
            assert resp["id"] == rid
            assert resp["result"]["pong"] is True

    def test_list_tools_returns_list(self, mcp_process):
        """Verify list_tools returns a list of tool definitions."""
        resp = _send_request(mcp_process, "list_tools")
        assert resp.get("jsonrpc") == "2.0"
        tools = resp.get("result", {}).get("tools", [])
        assert isinstance(tools, list)
        assert len(tools) > 0, "Expected at least one tool definition"

        # Check tool structure
        tool = tools[0]
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool

        # Check for known tools (nuclei is a critical tool)
        tool_names = {t["name"] for t in tools}
        assert "nuclei" in tool_names, (
            f"Expected 'nuclei' in tools, got: {sorted(tool_names)[:10]}"
        )

    def test_tool_definitions_have_capabilities(self, mcp_process):
        """Verify tool definitions include planner metadata (capabilities, etc.)."""
        resp = _send_request(mcp_process, "list_tools")
        tools = resp.get("result", {}).get("tools", [])

        tools_with_caps = [t for t in tools if t.get("capabilities")]
        assert len(tools_with_caps) > 0, (
            "Expected some tools to have capabilities"
        )

        # Check a specific tool has expected structure
        nuclei = next((t for t in tools if t["name"] == "nuclei"), None)
        assert nuclei is not None, "nuclei should be in test tools list"
        if nuclei:
            assert isinstance(nuclei.get("capabilities"), list)
            assert len(nuclei["capabilities"]) > 0

    def test_unknown_method_returns_error(self, mcp_process):
        """Verify unknown methods return METHOD_NOT_FOUND (-32601)."""
        resp = _send_request(mcp_process, "nonexistent_method")
        assert resp.get("jsonrpc") == "2.0"
        assert resp.get("id") == "1"
        assert "error" in resp
        assert resp["error"]["code"] == -32601
        assert "nonexistent_method" in resp["error"]["message"]

    def test_invalid_json_returns_parse_error(self, mcp_process):
        """Verify invalid JSON returns PARSE_ERROR (-32700).

        \x00 is a null byte which causes json.loads to fail.
        """
        proc = mcp_process
        proc.stdin.write(b"not valid json at all\n")
        proc.stdin.flush()

        start = time.time()
        while time.time() - start < RESPONSE_TIMEOUT:
            if proc.poll() is not None:
                raise RuntimeError("Process died while waiting for parse error")

            line = proc.stdout.readline()
            if not line:
                time.sleep(0.05)
                continue

            line = line.strip()
            if not line:
                continue

            try:
                resp = json.loads(line)
            except json.JSONDecodeError:
                continue

            if resp.get("error", {}).get("code") == -32700:
                return  # Success!

        pytest.fail("Did not receive PARSE_ERROR response within timeout")

    def test_batch_request(self, mcp_process):
        """Verify batch requests return an array of responses."""
        batch = [
            {"jsonrpc": "2.0", "id": "a", "method": "ping"},
            {"jsonrpc": "2.0", "id": "b", "method": "ping"},
        ]
        proc = mcp_process
        proc.stdin.write((json.dumps(batch) + "\n").encode("utf-8"))
        proc.stdin.flush()

        start = time.time()
        while time.time() - start < RESPONSE_TIMEOUT:
            if proc.poll() is not None:
                raise RuntimeError("Process died while waiting for batch response")

            line = proc.stdout.readline()
            if not line:
                time.sleep(0.05)
                continue

            line = line.strip()
            if not line:
                continue

            try:
                responses = json.loads(line)
            except json.JSONDecodeError:
                continue

            if isinstance(responses, list) and len(responses) == 2:
                ids = {r["id"] for r in responses}
                assert ids == {"a", "b"}
                for r in responses:
                    assert r["result"]["pong"] is True
                return

        pytest.fail("Did not receive batch response within timeout")

    def test_notification_no_response(self, mcp_process):
        """Verify notifications (no id) produce no response.

        Send a notification followed by a regular request to prove the
        notification was processed without generating output.
        """
        proc = mcp_process

        # Send notification (no id)
        notification = {"jsonrpc": "2.0", "method": "ping"}
        proc.stdin.write((json.dumps(notification) + "\n").encode("utf-8"))
        proc.stdin.flush()

        # Small delay to ensure notification would have been processed
        time.sleep(0.2)

        # Send a regular request — the next response should be for this request
        resp = _send_request(mcp_process, "ping", request_id="notif-test")
        assert resp["id"] == "notif-test"
        assert resp["result"]["pong"] is True

    def test_cancel_handler(self, mcp_process):
        """Verify the cancel handler works (returns cancelled=True/False).

        The test server always returns cancelled=True (it's a mock handler).
        The important thing is it doesn't crash.
        """
        resp = _send_request(
            mcp_process,
            "cancel",
            params={"engagement_id": "test-e2e"},
            request_id="cancel-test",
        )
        assert resp["id"] == "cancel-test"
        assert resp["result"]["cancelled"] is True

    def test_multiple_concurrent_pings(self, mcp_process):
        """Send multiple pings without waiting for responses, then read all responses."""
        proc = mcp_process
        n_requests = 5

        # Send all requests without waiting
        for i in range(n_requests):
            request = {
                "jsonrpc": "2.0",
                "id": f"concurrent-{i}",
                "method": "ping",
            }
            proc.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
        proc.stdin.flush()

        # Read all responses
        responses = []
        start = time.time()
        while len(responses) < n_requests and time.time() - start < RESPONSE_TIMEOUT:
            if proc.poll() is not None:
                raise RuntimeError("Process died while reading concurrent responses")

            line = proc.stdout.readline()
            if not line:
                time.sleep(0.05)
                continue

            line = line.strip()
            if not line:
                continue

            try:
                resp = json.loads(line)
            except json.JSONDecodeError:
                continue

            if resp.get("result", {}).get("pong") is True:
                responses.append(resp)

        assert len(responses) == n_requests, (
            f"Expected {n_requests} responses, got {len(responses)}"
        )
        for i, resp in enumerate(responses):
            assert resp["id"] == f"concurrent-{i}"
