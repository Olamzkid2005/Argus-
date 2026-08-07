"""
mcp_transport — stdio JSON-RPC transport for the MCP server.

Provides the JSON-RPC 2.0 wire protocol that bridges the TypeScript CLI
and the Python workers. Communication happens over stdin/stdout so the
TypeScript side can spawn the Python process as a child subprocess with
zero configuration — no network ports, no file sockets.

Usage:
    python -m mcp_server

Or from TypeScript:
    const child = spawn("python3", ["-m", "mcp_server"]);
    child.stdin.write(JSON.stringify({...}) + "\\n");
    child.stdout.on("data", ...);

Protocol:
    Request:  {"jsonrpc":"2.0","id":1,"method":"<name>","params":{...}}
    Response: {"jsonrpc":"2.0","id":1,"result":{...}}
    Error:    {"jsonrpc":"2.0","id":1,"error":{"code":N,"message":"..."}}
    Notification (no id): no response sent.

Handlers take ``params: dict | None`` and return a JSON-serializable dict.
"""

from __future__ import annotations

import json
import logging
import os
import select
import stat
import sys
import traceback
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# ── JSON-RPC 2.0 error codes ──

PARSE_ERROR = -32700       # Invalid JSON was received by the server
INVALID_REQUEST = -32600   # The JSON sent is not a valid Request object
METHOD_NOT_FOUND = -32601  # The method does not exist / is not available
INVALID_PARAMS = -32602    # Invalid method parameter(s)
INTERNAL_ERROR = -32603    # Internal JSON-RPC error

# ── Message size limits (blocker 39) ──
# Cap inbound request lines and outbound responses so a runaway tool output
# (e.g. a multi-GB nuclei/web_scanner line) can't OOM the worker or its
# parent process. Restored after the transport rewrite dropped both limits.
_MAX_MESSAGE_SIZE = 10 * 1024 * 1024    # inbound request line cap
_MAX_RESPONSE_SIZE = 50 * 1024 * 1024   # outbound response cap


def create_ping_handler() -> Callable[[dict | None], dict]:
    """Create a handler for the ``ping`` method.

    Returns:
        A callable that accepts ``params`` (ignored) and returns
        ``{"pong": True, "timestamp": <epoch_ms>}``.
    """
    import time as _time

    def _ping(params: dict | None = None) -> dict:
        return {"pong": True, "timestamp": int(_time.time() * 1000)}

    return _ping


class MCPTransport:
    """Stdio JSON-RPC 2.0 transport for the MCP server.

    Reads JSON-RPC requests from stdin (one JSON object per line) and
    writes responses to stdout. Single requests and batch arrays are both
    supported. Notifications (requests without an ``id`` field) never
    produce a response.

    Handlers are registered by name and receive a single ``params``
    argument (a dict or None). They may return any JSON-serializable value.

    Example::

        transport = MCPTransport()
        transport.register("ping", lambda p: {"pong": True})
        transport.register("list_tools", lambda p: {"tools": [...]})
        transport.run()
    """

    def __init__(
        self,
        stdin: Any | None = None,
        stdout: Any | None = None,
    ) -> None:
        self._handlers: dict[str, Callable[[dict | None], Any]] = {}
        self._running = False
        # Allow injecting fake streams for testing. Default to the real
        # stdio buffers so the subprocess parent communicates via pipes.
        self._stdin = stdin if stdin is not None else sys.stdin.buffer
        self._stdout = stdout if stdout is not None else sys.stdout.buffer

    def register(
        self,
        method: str,
        handler: Callable[[dict | None], Any],
    ) -> None:
        """Register a handler for the given JSON-RPC method name.

        Args:
            method: Method name (e.g. ``"ping"``, ``"call_tool"``).
            handler: Callable that accepts ``params: dict | None`` and
                     returns a JSON-serializable result.
        """
        self._handlers[method] = handler

    # ── Public lifecycle ──

    def _assert_stdio_only(self) -> None:
        """Defense-in-depth: warn (or hard-fail) if stdin/stdout are sockets.

        MCP is a stdio protocol; if stdin/stdout are network sockets the
        worker may have been accidentally exposed on the network. When
        ``ARGUS_MCP_BLOCK_SOCKET=1`` a socket detection raises instead of
        merely warning (blocker 62 regression guard).
        """
        _block = os.environ.get("ARGUS_MCP_BLOCK_SOCKET", "").lower() in ("1", "true")
        for _name, _stream in (("stdin", self._stdin), ("stdout", self._stdout)):
            try:
                _mode = os.fstat(_stream.fileno()).st_mode
            except (AttributeError, OSError, ValueError):
                continue  # injected fake streams in tests have no fileno
            if stat.S_ISSOCK(_mode):
                _msg = (
                    f"MCP transport {_name} is a network socket — expected a stdio pipe. "
                    "This worker should only be reachable over stdin/stdout."
                )
                if _block:
                    raise RuntimeError(_msg)
                logger.warning("%s", _msg)

    def _heartbeat_timeout_secs(self) -> float:
        """Return the idle-parent heartbeat timeout, or 0.0 to disable it.

        Controlled by ``ARGUS_MCP_HEARTBEAT_TIMEOUT_SECS`` (default 60).
        A value of 0 disables the watchdog entirely.
        """
        _raw = os.environ.get("ARGUS_MCP_HEARTBEAT_TIMEOUT_SECS", "60")
        try:
            return max(0.0, float(_raw))
        except ValueError:
            return 60.0

    def _wait_for_stdin(self, timeout: float) -> bool:
        """Wait up to ``timeout`` seconds for data on stdin via select().

        Returns True when data is ready, or when select() is unavailable
        (e.g. injected BytesIO streams in tests). Returns False when the
        timeout elapses with no data — the parent is presumed dead or stuck
        (blocker 62).
        """
        if timeout <= 0:
            return True  # heartbeat disabled
        try:
            _readable, _, _ = select.select([self._stdin], [], [], timeout)
        except (OSError, ValueError, TypeError) as e:
            logger.debug("MCP transport select() failed, proceeding without heartbeat: %s", e)
            return True
        return bool(_readable)

    def run(self) -> None:
        """Run the transport loop: read requests from stdin, write responses to stdout.

        The loop continues until EOF on stdin (pipe closed) or an
        unrecoverable error. SIGTERM/SIGINT are handled gracefully — the
        loop terminates after processing the current request.

        Guards (restored after the transport rewrite dropped them):
          - Bounded reads: inbound lines are capped at ``_MAX_MESSAGE_SIZE``
            (10 MB) so a runaway producer can't OOM the worker (blocker 39).
          - Outbound responses are capped at ``_MAX_RESPONSE_SIZE`` (50 MB)
            and truncated with a warning when exceeded.
          - Socket-mode detection on stdin/stdout (defense in depth).
          - Idle-parent heartbeat: if no request arrives within
            ``ARGUS_MCP_HEARTBEAT_TIMEOUT_SECS`` (default 60s), the parent is
            presumed dead and the worker shuts down instead of blocking
            forever (blocker 62). This also lets ``stop()`` interrupt a
            blocked read.

        Health endpoints (``/health``, ``/metrics``) are **not** served here;
        they are handled by ``health_server.py`` started separately in
        ``mcp_server.main()``.
        """
        self._running = True
        self._assert_stdio_only()
        _heartbeat = self._heartbeat_timeout_secs()

        # Read lines from stdin (one JSON-RPC request per line).
        # Use self._stdin for raw bytes to avoid encoding issues,
        # then decode as UTF-8 (the JSON-RPC spec requires UTF-8).
        stdin = self._stdin
        stdout = self._stdout

        while self._running:
            # Idle-parent watchdog — also gives stop() a bounded window.
            if not self._wait_for_stdin(_heartbeat):
                logger.warning(
                    "MCP transport: no data from parent for %.0fs — parent may be dead, shutting down",
                    _heartbeat,
                )
                break

            try:
                line = stdin.readline(_MAX_MESSAGE_SIZE + 1)
            except (OSError, ValueError) as e:
                logger.error("MCP transport read error: %s", e)
                break

            if not line:
                # EOF — parent process closed the pipe
                logger.info("MCP transport: stdin closed, shutting down")
                break

            if len(line) > _MAX_MESSAGE_SIZE:
                self._send_error(
                    stdout,
                    None,
                    INVALID_REQUEST,
                    f"Message exceeds max size ({_MAX_MESSAGE_SIZE} bytes)",
                )
                # Drain the remainder of the oversized line so the next
                # read starts at a clean boundary.
                while line and not line.endswith(b"\n"):
                    line = stdin.readline(_MAX_MESSAGE_SIZE + 1)
                continue

            line = line.strip()
            if not line:
                continue

            # Handle individual request or batch
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                self._send_error(
                    stdout,
                    None,
                    PARSE_ERROR,
                    "Parse error: invalid JSON",
                )
                continue

            if isinstance(raw, list):
                if not raw:
                    # JSON-RPC 2.0: an empty batch must be answered with a
                    # single Invalid Request error.
                    self._send_error(
                        stdout,
                        None,
                        INVALID_REQUEST,
                        "Invalid Request: empty batch",
                    )
                    continue
                # Batch — process each request, collect responses
                responses = []
                for req in raw:
                    resp = self._process_request(req)
                    if resp is not None:
                        responses.append(resp)
                if responses:
                    self._write_json(stdout, responses)
            else:
                # Single request
                resp = self._process_request(raw)
                if resp is not None:
                    self._write_json(stdout, resp)

        self._running = False

    def stop(self) -> None:
        """Signal the transport loop to stop at the next iteration.

        With the idle-parent heartbeat enabled, ``run()`` polls stdin via
        ``select()`` so ``stop()`` takes effect within one heartbeat window
        instead of blocking on a hung readline().
        """
        self._running = False

    # ── Request processing ──

    def _process_request(self, raw: Any) -> dict | None:
        """Process a single decoded JSON-RPC request.

        Args:
            raw: Decoded JSON value (should be a dict).

        Returns:
            A response dict, or ``None`` for notifications.
        """
        if not isinstance(raw, dict):
            return self._make_error(
                None,
                INVALID_REQUEST,
                "Invalid Request: must be a JSON object",
            )

        request_id = raw.get("id")
        method = raw.get("method", "")
        params = raw.get("params")

        # Validate required fields
        if not isinstance(method, str) or not method:
            return self._make_error(
                request_id,
                INVALID_REQUEST,
                "Invalid Request: 'method' must be a non-empty string",
            )

        # Notifications (no id) — no response
        if request_id is None:
            self._handle_notification(method, params)
            return None

        # Look up handler
        handler = self._handlers.get(method)
        if handler is None:
            return self._make_error(
                request_id,
                METHOD_NOT_FOUND,
                f"Method not found: {method}",
            )

        # Call handler
        try:
            result = handler(params)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result,
            }
        except Exception as e:
            logger.error(
                "Handler '%s' raised: %s\n%s",
                method,
                e,
                traceback.format_exc(),
            )
            return self._make_error(
                request_id,
                INTERNAL_ERROR,
                f"Internal error: {e}",
            )

    def _handle_notification(self, method: str, params: Any) -> None:
        """Process a notification (request without id). Logged but not handled."""
        handler = self._handlers.get(method)
        if handler is not None:
            try:
                handler(params)
            except Exception:
                logger.debug(
                    "Notification handler '%s' failed (silently ignored):",
                    method,
                    exc_info=True,
                )
        else:
            logger.debug("Unhandled notification: %s", method)

    # ── Response helpers ──

    def _make_error(
        self,
        request_id: Any,
        code: int,
        message: str,
    ) -> dict:
        """Build a JSON-RPC error response dict."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message,
            },
        }

    def _send_error(
        self,
        stdout: Any,
        request_id: Any,
        code: int,
        message: str,
    ) -> None:
        """Build and write a JSON-RPC error response."""
        resp = self._make_error(request_id, code, message)
        self._write_json(stdout, resp)

    def _write_json(self, stdout: Any, obj: Any) -> None:
        """Serialize ``obj`` as JSON and write it as a single line to stdout.

        Uses ``sys.stdout.buffer`` for raw bytes to avoid the encoding
        layer adding extra newlines or mangling binary-safe strings.

        Always appends ``\\n`` so the reader can split on newlines. Flushes
        after every write to ensure the parent process receives responses
        without buffering delay.

        Enforces ``_MAX_RESPONSE_SIZE`` (50 MB): oversized payloads (e.g.
        giant tool outputs) are truncated to a warning stub so the parent
        can't OOM (blocker 39). Non-serializable handler results surface as
        -32603 instead of being silently stringified.
        """
        try:
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n"
        except (TypeError, ValueError) as e:
            # Handler returned something JSON can't serialize — surface as
            # an internal error rather than silently stringifying it.
            logger.error("MCP transport: response is not JSON-serializable: %s", e)
            request_id = obj.get("id") if isinstance(obj, dict) else None
            data = json.dumps(
                self._make_error(
                    request_id,
                    INTERNAL_ERROR,
                    f"Response is not JSON-serializable: {e}",
                ),
                ensure_ascii=False,
            ).encode("utf-8") + b"\n"

        if len(data) > _MAX_RESPONSE_SIZE:
            logger.warning(
                "MCP transport: response exceeds %d bytes (%d) — truncating",
                _MAX_RESPONSE_SIZE,
                len(data),
            )
            request_id = obj.get("id") if isinstance(obj, dict) else None
            data = json.dumps(
                self._make_error(
                    request_id,
                    INTERNAL_ERROR,
                    f"Response too large ({len(data)} bytes, max {_MAX_RESPONSE_SIZE})",
                ),
                ensure_ascii=False,
            ).encode("utf-8") + b"\n"

        try:
            stdout.write(data)
            stdout.flush()
        except (OSError, ValueError) as e:
            # If the parent has closed its stdin, we can't write.
            # This is common during shutdown — log and stop.
            logger.debug("MCP transport write error (parent may have closed pipe): %s", e)
            self._running = False
