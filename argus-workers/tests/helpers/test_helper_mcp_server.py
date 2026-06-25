"""Minimal MCP server for integration tests.

Responds to:
  - ping → "pong"
  - list_tools → a minimal tool list with an "echo" tool
  - call_tool → for "echo", echoes back the message; for others, returns error

This is NOT a full MCP server — it's a lightweight test double that
exercises the real JSON-RPC stdin/stdout transport layer.
"""

import json
import sys
import time


def handle_request(request: dict) -> dict:
    """Handle a JSON-RPC request and return a response dict."""
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {}) or {}

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": "pong"}

    if method == "list_tools":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echoes back the message parameter",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "message": {
                                    "type": "string",
                                    "description": "Message to echo",
                                }
                            },
                            "required": ["message"],
                        },
                        "capabilities": [],
                    }
                ]
            },
        }

    if method == "call_tool":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {}) or {}

        if tool_name == "echo":
            msg = arguments.get("message", "")
            duration = arguments.get("sleep_ms", 0)
            if duration:
                time.sleep(duration / 1000.0)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": msg}],
                    "isError": False,
                    "meta": {
                        "success": True,
                        "duration_ms": int(duration),
                        "tool": "echo",
                        "signal_quality": "CONFIRMED",
                    },
                },
            }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
                "isError": True,
                "meta": {"success": False, "duration_ms": 0, "tool": tool_name},
            },
        }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main():
    """Read JSON-RPC requests from stdin, write responses to stdout."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = handle_request(request)
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
        except (json.JSONDecodeError, KeyError) as e:
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {e}"},
            }
            sys.stdout.write(json.dumps(error_response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
