"""
MCP stdio JSON-RPC Transport

Implements the JSON-RPC 2.0 wire protocol over stdio for communication
between the TypeScript CLI and Python worker processes.

Protocol:
  - Requests: JSON-RPC 2.0 objects written to stdin (one per line)
  - Responses: JSON-RPC 2.0 objects written to stdout (one per line)
  - Logging: stderr for diagnostics (never stdout)
  - Line delimiter: LF (\\n)

Methods:
  - ping → "pong" (health check)
  - list_tools → ToolDefinition[]
  - call_tool → ToolResult
"""

import json
import logging
import sys
import traceback
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class MCPTransportError(Exception):
    pass


class MCPTransport:
    def __init__(self):
        self.handlers: dict[str, Callable] = {}
        self._running = False

    def register(self, method: str, handler: Callable):
        self.handlers[method] = handler

    def _read_request(self) -> dict | None:
        line = sys.stdin.readline()
        if not line:
            return None
        try:
            return json.loads(line.strip())
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON-RPC request: %s", e)
            return None

    def _send_response(self, request: dict, result: Any = None, error: dict | None = None):
        response = {"jsonrpc": "2.0", "id": request.get("id")}
        if error:
            response["error"] = error
        else:
            response["result"] = result
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()

    def _handle_request(self, request: dict):
        method = request.get("method")
        params = request.get("params", {})

        if not method:
            self._send_response(request, error={"code": -32600, "message": "Method not specified"})
            return

        handler = self.handlers.get(method)
        if not handler:
            self._send_response(request, error={
                "code": -32601, "message": f"Method not found: {method}",
            })
            return

        try:
            result = handler(params)
            self._send_response(request, result=result)
        except Exception as e:
            logger.error("Handler error for %s: %s", method, traceback.format_exc())
            self._send_response(request, error={
                "code": -32603, "message": str(e),
            })

    def run(self):
        self._running = True
        while self._running:
            try:
                request = self._read_request()
                if request is None:
                    break
                self._handle_request(request)
            except KeyboardInterrupt:
                break
            except Exception:
                logger.error("Transport error: %s", traceback.format_exc())
                break


def create_ping_handler():
    def ping(params: dict) -> str:
        return "pong"
    return ping
