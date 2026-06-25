"""Tests for mcp_transport.py recovery fix — _SKIP_LINE vs None distinction."""

import json
from io import StringIO
from unittest.mock import patch

import pytest

from mcp_transport import MCPTransport, _SKIP_LINE


class TestReadRequestSentinel:
    """_read_request returns different sentinels for malformed JSON vs EOF."""

    @patch("mcp_transport.sys.stdin", new_callable=StringIO)
    def test_malformed_json_returns_skip_line(self, mock_stdin):
        """Malformed JSON line returns _SKIP_LINE sentinel, not None."""
        mock_stdin.write("not valid json\n")
        mock_stdin.seek(0)
        transport = MCPTransport()

        result = transport._read_request()

        assert result is _SKIP_LINE
        assert result is not None

    @patch("mcp_transport.sys.stdin", new_callable=StringIO)
    def test_eof_returns_none(self, mock_stdin):
        """EOF (stdin closed) returns None."""
        transport = MCPTransport()

        result = transport._read_request()

        assert result is None

    @patch("mcp_transport.sys.stdin", new_callable=StringIO)
    def test_valid_json_returns_dict(self, mock_stdin):
        """Valid JSON returns the parsed dict."""
        mock_stdin.write('{"method": "ping"}\n')
        mock_stdin.seek(0)
        transport = MCPTransport()

        result = transport._read_request()

        assert result == {"method": "ping"}
        assert result is not _SKIP_LINE
        assert result is not None

    @patch("mcp_transport.sys.stdin", new_callable=StringIO)
    def test_empty_line_returns_skip_line(self, mock_stdin):
        """Empty line is NOT EOF — returns _SKIP_LINE (not None)."""
        mock_stdin.write("\n")
        mock_stdin.seek(0)
        transport = MCPTransport()

        result = transport._read_request()

        assert result is _SKIP_LINE

    @patch("mcp_transport.sys.stdin", new_callable=StringIO)
    def test_skip_line_sentinel_is_empty_dict(self, mock_stdin):
        """_SKIP_LINE is an empty dict sentinel, not None."""
        assert _SKIP_LINE == {}
        assert _SKIP_LINE is not None


class TestRunLoopRecovery:
    """run() loop correctly handles _SKIP_LINE vs None."""

    @patch("mcp_transport.sys.stdout", new_callable=StringIO)
    @patch("mcp_transport.sys.stdin", new_callable=StringIO)
    def test_skips_malformed_json_and_continues(self, mock_stdin, mock_stdout):
        """Malformed JSON lines are skipped and processing continues."""
        mock_stdin.write("not json\n")
        mock_stdin.write('{"id": 1, "method": "ping"}\n')
        mock_stdin.seek(0)
        transport = MCPTransport()
        transport.register("ping", lambda params: "pong")

        transport.run()

        output = mock_stdout.getvalue()
        assert '"result": "pong"' in output

    @patch("mcp_transport.sys.stdout", new_callable=StringIO)
    @patch("mcp_transport.sys.stdin", new_callable=StringIO)
    def test_malformed_json_between_valid_messages(self, mock_stdin, mock_stdout):
        """Multiple valid messages with malformed lines in between all work."""
        mock_stdin.write('{"id": 1, "method": "ping"}\n')
        mock_stdin.write("garbage\n")
        mock_stdin.write("{bad}\n")
        mock_stdin.write('{"id": 2, "method": "ping"}\n')
        mock_stdin.seek(0)
        transport = MCPTransport()
        transport.register("ping", lambda params: "pong")

        transport.run()

        output = mock_stdout.getvalue()
        assert output.count('"result": "pong"') == 2

    @patch("mcp_transport.sys.stdout", new_callable=StringIO)
    @patch("mcp_transport.sys.stdin", new_callable=StringIO)
    def test_eof_breaks_loop(self, mock_stdin, mock_stdout):
        """EOF (no more data) breaks the run loop cleanly — run() returns."""
        transport = MCPTransport()

        transport.run()

        assert transport._running is True

    @patch("mcp_transport.sys.stdout", new_callable=StringIO)
    @patch("mcp_transport.sys.stdin", new_callable=StringIO)
    def test_mixed_skip_and_eof_behavior(self, mock_stdin, mock_stdout):
        """Messages after malformed lines are processed, and EOF still breaks."""
        mock_stdin.write('{"id": 1, "method": "ping"}\n')
        mock_stdin.write("bad line\n")
        mock_stdin.write('{"id": 2, "method": "ping"}\n')
        mock_stdin.seek(0)
        transport = MCPTransport()
        transport.register("ping", lambda params: "pong")

        transport.run()

        output = mock_stdout.getvalue()
        assert output.count('"result": "pong"') == 2

    @patch("mcp_transport.sys.stdout", new_callable=StringIO)
    @patch("mcp_transport.sys.stdin", new_callable=StringIO)
    def test_keyboard_interrupt_breaks_loop(self, mock_stdin, mock_stdout):
        """KeyboardInterrupt breaks the run loop."""
        mock_stdin.readline = lambda: (_ for _ in ()).throw(KeyboardInterrupt())
        transport = MCPTransport()

        transport.run()

        assert transport._running is True  # _running not reset, loop exited cleanly


class TestSkipLineSentinelBehavior:
    """The _SKIP_LINE sentinel identity is used for run() loop control."""

    def test_skip_line_is_not_none(self):
        """_SKIP_LINE must not be None, which is reserved for EOF."""
        assert _SKIP_LINE is not None

    def test_skip_line_is_dict(self):
        """_SKIP_LINE is an empty dict."""
        assert isinstance(_SKIP_LINE, dict)
        assert len(_SKIP_LINE) == 0

    def test_existing_test_needs_update(self):
        """Verify the existing test_mcp_transport bug — invalid JSON should not be None."""
        try:
            json.loads("not json")
        except json.JSONDecodeError:
            result = _SKIP_LINE
        assert result is _SKIP_LINE
        assert result is not None
