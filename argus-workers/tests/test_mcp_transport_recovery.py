"""Tests for mcp_transport.py run-loop recovery — malformed JSON handling.

Verifies that a single malformed JSON line does NOT kill the transport loop:
it is answered with a JSON-RPC PARSE_ERROR response and processing continues,
while genuine EOF (stdin closed) still exits the loop cleanly.

These tests exercise the real ``MCPTransport.run()`` via injected BytesIO
streams (same pattern as test_mcp_transport.py).
"""

from __future__ import annotations

import io
import json

from mcp_transport import PARSE_ERROR, MCPTransport


def _run(input_data: bytes):
    """Build a transport with fake streams and run it, returning stdout bytes."""
    fake_stdin = io.BytesIO(input_data)
    fake_stdout = io.BytesIO()
    transport = MCPTransport(stdin=fake_stdin, stdout=fake_stdout)
    transport.register("ping", lambda _params: {"pong": True})
    transport.run()
    fake_stdout.seek(0)
    return fake_stdout.read()


def _responses(output: bytes) -> list[dict]:
    """Parse newline-delimited JSON responses from captured stdout."""
    return [json.loads(line) for line in output.strip().split(b"\n") if line.strip()]


class TestMalformedJsonRecovery:
    """Malformed JSON lines are answered with a PARSE_ERROR, loop continues."""

    def test_malformed_json_returns_parse_error(self):
        """A malformed JSON line produces a PARSE_ERROR response, not a crash."""
        output = _run(b"not valid json\n")
        responses = _responses(output)
        assert len(responses) == 1
        assert responses[0]["error"]["code"] == PARSE_ERROR

    def test_skips_malformed_json_and_continues(self):
        """A malformed line does not prevent later valid requests from being processed."""
        output = _run(b"not json\n" + b'{"id": 1, "method": "ping"}\n')
        responses = _responses(output)
        pongs = [r for r in responses if r.get("result") == {"pong": True}]
        assert len(pongs) == 1
        assert pongs[0]["id"] == 1

    def test_malformed_json_between_valid_messages(self):
        """Multiple valid messages with malformed lines in between all work."""
        data = (
            b'{"id": 1, "method": "ping"}\n'
            b"garbage\n"
            b"{bad}\n"
            b'{"id": 2, "method": "ping"}\n'
        )
        responses = _responses(_run(data))
        pongs = [r for r in responses if r.get("result") == {"pong": True}]
        assert len(pongs) == 2

    def test_empty_lines_are_skipped(self):
        """Blank lines are ignored silently (no response, no crash)."""
        output = _run(b"\n\n" + b'{"id": 1, "method": "ping"}\n')
        responses = _responses(output)
        assert len(responses) == 1
        assert responses[0]["id"] == 1


class TestRunLoopEof:
    """EOF (stdin closed) exits the run loop cleanly."""

    def test_eof_breaks_loop(self):
        """Empty input (EOF immediately) returns without hanging."""
        output = _run(b"")
        assert output == b""

    def test_eof_after_messages_breaks_loop(self):
        """Processing completes, then EOF ends the loop."""
        output = _run(b'{"id": 1, "method": "ping"}\n')
        responses = _responses(output)
        assert len(responses) == 1
        assert responses[0]["result"] == {"pong": True}

    def test_mixed_skip_and_eof_behavior(self):
        """Messages after malformed lines are processed, and EOF still breaks."""
        data = (
            b'{"id": 1, "method": "ping"}\n'
            b"bad line\n"
            b'{"id": 2, "method": "ping"}\n'
        )
        responses = _responses(_run(data))
        pongs = [r for r in responses if r.get("result") == {"pong": True}]
        assert len(pongs) == 2
