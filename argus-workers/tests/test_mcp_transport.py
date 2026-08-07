"""
Tests for mcp_transport.py — stdio JSON-RPC 2.0 transport layer.

Covers:
  - create_ping_handler()
  - MCPTransport._process_request() — single requests, notifications, errors
  - MCPTransport._make_error() — error format
  - MCPTransport.register() — handler lifecycle
  - MCPTransport.run() — integration with fake stdin/stdout streams
  - Edge cases: invalid JSON, unknown methods, handler exceptions, batch requests
"""

from __future__ import annotations

import io
import json

import pytest

from mcp_transport import (
    INTERNAL_ERROR,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    MCPTransport,
    create_ping_handler,
)


class TestCreatePingHandler:
    """Tests for create_ping_handler()."""

    def test_returns_pong(self):
        handler = create_ping_handler()
        result = handler({})
        assert result["pong"] is True
        assert "timestamp" in result
        assert isinstance(result["timestamp"], int)

    def test_handles_none_params(self):
        handler = create_ping_handler()
        result = handler(None)
        assert result["pong"] is True


class TestMCPTransportProcessRequest:
    """Tests for MCPTransport._process_request() — no I/O needed."""

    @pytest.fixture
    def transport(self):
        t = MCPTransport()
        t.register("echo", lambda params: params or {})
        t.register("fail", lambda _params: (_ for _ in ()).throw(ValueError("oops")))
        return t

    def test_valid_request(self, transport):
        resp = transport._process_request({
            "jsonrpc": "2.0",
            "id": "1",
            "method": "echo",
            "params": {"key": "value"},
        })
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == "1"
        assert resp["result"] == {"key": "value"}

    def test_notification_no_response(self, transport):
        resp = transport._process_request({
            "jsonrpc": "2.0",
            "method": "echo",
            "params": {"key": "value"},
        })
        assert resp is None

    def test_notification_unknown_method_no_error(self, transport):
        """Notifications with unknown methods should not produce errors."""
        resp = transport._process_request({
            "jsonrpc": "2.0",
            "method": "nonexistent",
        })
        assert resp is None

    def test_unknown_method(self, transport):
        resp = transport._process_request({
            "jsonrpc": "2.0",
            "id": "1",
            "method": "nonexistent",
        })
        assert resp["error"]["code"] == METHOD_NOT_FOUND
        assert "nonexistent" in resp["error"]["message"]

    def test_handler_exception(self, transport):
        resp = transport._process_request({
            "jsonrpc": "2.0",
            "id": "1",
            "method": "fail",
        })
        assert resp["error"]["code"] == INTERNAL_ERROR
        assert "oops" in resp["error"]["message"]

    def test_not_a_dict(self, transport):
        resp = transport._process_request("not a dict")
        assert resp["error"]["code"] == INVALID_REQUEST
        assert "must be a JSON object" in resp["error"]["message"]

    def test_missing_method(self, transport):
        resp = transport._process_request({
            "jsonrpc": "2.0",
            "id": "1",
        })
        assert resp["error"]["code"] == INVALID_REQUEST
        assert "method" in resp["error"]["message"]

    def test_empty_method(self, transport):
        resp = transport._process_request({
            "jsonrpc": "2.0",
            "id": "1",
            "method": "",
        })
        assert resp["error"]["code"] == INVALID_REQUEST
        assert "method" in resp["error"]["message"]


class TestMCPTransportMakeError:
    """Tests for _make_error()."""

    def test_error_format(self):
        transport = MCPTransport()
        err = transport._make_error("req-1", -32000, "Custom error")
        assert err["jsonrpc"] == "2.0"
        assert err["id"] == "req-1"
        assert err["error"]["code"] == -32000
        assert err["error"]["message"] == "Custom error"

    def test_error_with_none_id(self):
        transport = MCPTransport()
        err = transport._make_error(None, PARSE_ERROR, "Parse error")
        assert err["id"] is None


class TestMCPTransportRun:
    """Integration tests for MCPTransport.run() using fake streams.

    The transport accepts optional ``stdin``/``stdout`` parameters so we
    can pass BytesIO objects directly without patching sys.stdin/sys.stdout.
    """

    def _make_input(self, requests) -> bytes:
        """Serialize one or more JSON-RPC requests as newline-delimited JSON."""
        lines = [json.dumps(req) for req in requests]
        return ("\n".join(lines) + "\n").encode("utf-8")

    def _run(self, input_data: bytes):
        """Build a transport with fake streams and run it.

        Returns the captured stdout content as bytes.
        """
        fake_stdin = io.BytesIO(input_data)
        fake_stdout = io.BytesIO()
        transport = MCPTransport(stdin=fake_stdin, stdout=fake_stdout)
        transport.register("ping", create_ping_handler())
        transport.register("echo", lambda params: params or {})
        transport.run()
        fake_stdout.seek(0)
        return fake_stdout.read()

    def test_ping_request(self):
        output = self._run(self._make_input([
            {"jsonrpc": "2.0", "id": "1", "method": "ping"},
        ]))
        lines = output.strip().split(b"\n")
        assert len(lines) == 1
        resp = json.loads(lines[0])
        assert resp["id"] == "1"
        assert resp["result"]["pong"] is True

    def test_echo_request(self):
        output = self._run(self._make_input([
            {"jsonrpc": "2.0", "id": "2", "method": "echo", "params": {"hello": "world"}},
        ]))
        resp = json.loads(output.strip())
        assert resp["result"]["hello"] == "world"

    def test_unknown_method(self):
        output = self._run(self._make_input([
            {"jsonrpc": "2.0", "id": "3", "method": "unknown_tool"},
        ]))
        resp = json.loads(output.strip())
        assert resp["error"]["code"] == METHOD_NOT_FOUND
        assert "unknown_tool" in resp["error"]["message"]

    def test_notification_no_output(self):
        """Notifications should produce no response."""
        output = self._run(self._make_input([
            {"jsonrpc": "2.0", "method": "ping"},
        ]))
        assert output.strip() == b""

    def test_mixed_notifications_and_requests(self):
        """Notifications don't produce responses; requests do."""
        output = self._run(self._make_input([
            {"jsonrpc": "2.0", "method": "ping"},          # notification — no response
            {"jsonrpc": "2.0", "id": "1", "method": "ping"},  # request — response
            {"jsonrpc": "2.0", "method": "echo"},          # notification — no response
            {"jsonrpc": "2.0", "id": "2", "method": "echo", "params": {"x": 1}},  # response
        ]))
        lines = [line for line in output.strip().split(b"\n") if line]
        assert len(lines) == 2
        resp1 = json.loads(lines[0])
        resp2 = json.loads(lines[1])
        assert resp1["id"] == "1"
        assert resp1["result"]["pong"] is True
        assert resp2["id"] == "2"
        assert resp2["result"]["x"] == 1

    def test_batch_request(self):
        """Batch of requests returns an array of responses."""
        output = self._run(self._make_input([
            [
                {"jsonrpc": "2.0", "id": "a", "method": "ping"},
                {"jsonrpc": "2.0", "id": "b", "method": "echo", "params": {"n": 42}},
                {"jsonrpc": "2.0", "method": "ping"},  # notification — skipped in batch
            ],
        ]))
        responses = json.loads(output.strip())
        assert isinstance(responses, list)
        assert len(responses) == 2  # notification produces no response
        ids = {r["id"] for r in responses}
        assert ids == {"a", "b"}
        assert responses[1]["result"]["n"] == 42

    def test_batch_notifications_only(self):
        """A batch with only notifications produces no output."""
        output = self._run(self._make_input([
            [
                {"jsonrpc": "2.0", "method": "ping"},
                {"jsonrpc": "2.0", "method": "echo", "params": {"x": 1}},
            ],
        ]))
        assert output.strip() == b""

    def test_empty_input(self):
        """Empty or whitespace-only lines should be skipped."""
        output = self._run(b"\n\n  \n")
        assert output.strip() == b""

    def test_invalid_json(self):
        output = self._run(b"not-json\n")
        resp = json.loads(output.strip())
        assert resp["error"]["code"] == PARSE_ERROR

    def test_multiple_requests(self):
        output = self._run(self._make_input([
            {"jsonrpc": "2.0", "id": "1", "method": "ping"},
            {"jsonrpc": "2.0", "id": "2", "method": "echo", "params": {"a": 1}},
            {"jsonrpc": "2.0", "id": "3", "method": "unknown"},
        ]))
        lines = [line for line in output.strip().split(b"\n") if line]
        assert len(lines) == 3
        assert json.loads(lines[0])["result"]["pong"] is True
        assert json.loads(lines[1])["result"]["a"] == 1
        assert json.loads(lines[2])["error"]["code"] == METHOD_NOT_FOUND


class TestMCPTransportRegister:
    """Tests for register()."""

    def test_register_and_call_via_process(self):
        transport = MCPTransport()
        transport.register("add", lambda params: {"sum": params["x"] + params["y"]})

        resp = transport._process_request({
            "jsonrpc": "2.0",
            "id": "1",
            "method": "add",
            "params": {"x": 3, "y": 4},
        })
        assert resp["result"]["sum"] == 7

    def test_register_overwrites_existing(self):
        transport = MCPTransport()
        transport.register("method", lambda _p: {"from": "first"})
        transport.register("method", lambda _p: {"from": "second"})
        resp = transport._process_request({
            "jsonrpc": "2.0",
            "id": "1",
            "method": "method",
        })
        assert resp["result"]["from"] == "second"
