"""Tests for mcp_transport.py — MCPTransport, create_ping_handler."""

from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from mcp_transport import MCPTransport, create_ping_handler


class TestMCPTransport:
    def test_register_stores_handler(self):
        transport = MCPTransport()
        handler = MagicMock()
        transport.register("test", handler)
        assert transport.handlers["test"] == handler

    @patch("mcp_transport.sys.stdin", new_callable=StringIO)
    def test_read_request_parses_json(self, mock_stdin):
        mock_stdin.write('{"method": "ping"}\n')
        mock_stdin.seek(0)
        transport = MCPTransport()
        result = transport._read_request()
        assert result == {"method": "ping"}

    @patch("mcp_transport.sys.stdin", new_callable=StringIO)
    def test_read_request_returns_none_for_empty_line(self, mock_stdin):
        mock_stdin.write("\n")
        mock_stdin.seek(0)
        transport = MCPTransport()
        result = transport._read_request()
        assert result is None

    @patch("mcp_transport.sys.stdin", new_callable=StringIO)
    def test_read_request_returns_none_for_invalid_json(self, mock_stdin):
        mock_stdin.write("not json\n")
        mock_stdin.seek(0)
        transport = MCPTransport()
        result = transport._read_request()
        assert result is None

    @patch("mcp_transport.sys.stdout", new_callable=StringIO)
    def test_send_response_writes_result(self, mock_stdout):
        transport = MCPTransport()
        transport._send_response({"id": 1}, result="pong")
        output = mock_stdout.getvalue()
        assert '"jsonrpc": "2.0"' in output
        assert '"result": "pong"' in output
        assert '"id": 1' in output

    @patch("mcp_transport.sys.stdout", new_callable=StringIO)
    def test_send_response_writes_error(self, mock_stdout):
        transport = MCPTransport()
        transport._send_response(
            {"id": 1},
            error={"code": -32601, "message": "Method not found"},
        )
        output = mock_stdout.getvalue()
        assert '"error"' in output
        assert '-32601' in output
        assert '"result"' not in output

    @patch("mcp_transport.sys.stdout", new_callable=StringIO)
    @patch("mcp_transport.sys.stdin", new_callable=StringIO)
    def test_handle_request_dispatches_to_handler(self, mock_stdin, mock_stdout):
        transport = MCPTransport()
        transport.register("ping", create_ping_handler())
        transport._handle_request({"id": 1, "method": "ping"})
        output = mock_stdout.getvalue()
        assert '"result": "pong"' in output

    @patch("mcp_transport.sys.stdout", new_callable=StringIO)
    def test_handle_request_returns_32601_for_unknown_method(self, mock_stdout):
        transport = MCPTransport()
        transport._handle_request({"id": 1, "method": "unknown"})
        output = mock_stdout.getvalue()
        assert '-32601' in output
        assert 'Method not found' in output

    @patch("mcp_transport.sys.stdout", new_callable=StringIO)
    def test_handle_request_returns_32600_for_missing_method(self, mock_stdout):
        transport = MCPTransport()
        transport._handle_request({"id": 1})
        output = mock_stdout.getvalue()
        assert '-32600' in output
        assert 'Method not specified' in output

    @patch("mcp_transport.sys.stdout", new_callable=StringIO)
    def test_handle_request_returns_32603_on_handler_exception(self, mock_stdout):
        def failing_handler(params):
            raise ValueError("oops")

        transport = MCPTransport()
        transport.register("fail", failing_handler)
        transport._handle_request({"id": 1, "method": "fail"})
        output = mock_stdout.getvalue()
        assert '-32603' in output
        assert 'oops' in output

    @patch("mcp_transport.sys.stdout", new_callable=StringIO)
    @patch("mcp_transport.sys.stdin", new_callable=StringIO)
    def test_run_reads_and_handles_requests(self, mock_stdin, mock_stdout):
        mock_stdin.write('{"id": 1, "method": "ping"}\n')
        mock_stdin.write('{"id": 2, "method": "ping"}\n')
        mock_stdin.seek(0)
        transport = MCPTransport()
        transport.register("ping", create_ping_handler())
        transport.run()
        output = mock_stdout.getvalue()
        assert output.count('"result": "pong"') == 2

    @patch("mcp_transport.sys.stdin", new_callable=StringIO)
    def test_run_breaks_on_none_request(self, mock_stdin):
        transport = MCPTransport()
        transport.run()

    @patch("mcp_transport.sys.stdin", new_callable=StringIO)
    def test_run_breaks_on_keyboard_interrupt(self, mock_stdin):
        mock_stdin.readline = MagicMock(side_effect=KeyboardInterrupt())
        transport = MCPTransport()
        transport.run()

    def test_create_ping_handler_returns_pong(self):
        handler = create_ping_handler()
        assert handler({}) == "pong"
