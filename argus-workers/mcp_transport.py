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



# Sentinel used by _read_request to signal a malformed JSON line that should
# be skipped (continue) rather than treated as EOF (break).
_SKIP_LINE: dict = {}


class MCPTransport:
    def __init__(self):
        self.handlers: dict[str, Callable] = {}
        self._running = False

    def register(self, method: str, handler: Callable):
        self.handlers[method] = handler

    def _read_request(self) -> dict | None:
        """Read and parse one JSON-RPC request from stdin.

        Returns:
            dict: Parsed request on success.
            None: EOF (stdin closed) — caller should exit the run loop.
            _SKIP_LINE: Malformed JSON — caller should continue to next line.
        """
        line = sys.stdin.readline()
        if not line:
            return None
        try:
            return json.loads(line.strip())
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON-RPC request: %s", e)
            return _SKIP_LINE

    def _send_response(
        self, request: dict, result: Any = None, error: dict | None = None
    ):
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
            self._send_response(
                request, error={"code": -32600, "message": "Method not specified"}
            )
            return

        handler = self.handlers.get(method)
        if not handler:
            self._send_response(
                request,
                error={
                    "code": -32601,
                    "message": f"Method not found: {method}",
                },
            )
            return

        try:
            result = handler(params)
            self._send_response(request, result=result)
        except Exception as e:
            logger.error("Handler error for %s: %s", method, traceback.format_exc())
            err_msg = str(e)
            err_lower = err_msg.lower()
            # Classify errors so the TS side can use structured codes instead
            # of fragile string matching on the error message.
            error_type = "internal_error"
            if any(kw in err_lower for kw in ("llm", "openai", "anthropic", "ai provider", "ai model")):
                error_type = "llm_error"
            self._send_response(
                request,
                error={
                    "code": -32603,
                    "message": err_msg,
                    "data": {"error_type": error_type},
                },
            )

    def run(self):
        self._running = True
        while self._running:
            try:
                request = self._read_request()
                if request is None:
                    break  # EOF — stdin closed
                if request is _SKIP_LINE:
                    continue  # malformed JSON — skip and keep reading
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
