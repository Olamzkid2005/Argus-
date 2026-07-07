"""
Health & Metrics HTTP Server for the MCP Worker (blocker 57).

Exposes a lightweight HTTP endpoint so Docker/k8s health probes and
operators can check worker liveness and view runtime metrics without
needing to parse stderr logs.

Endpoints:
  GET /health  — {"status": "ok"|"degraded", "uptime_seconds": N, ...}
  GET /metrics — Detailed JSON with tool stats, pool state, sessions

Uses Python's built-in http.server — no extra dependencies.
Runs on a daemon thread that does not block stdio transport shutdown.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time as _time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

logger = logging.getLogger(__name__)

# Default bind address: localhost only (never expose the metrics port to the network).
# NOTE: kept as raw strings so int("") doesn't crash on import when the env var
# is empty (which is the signal to disable the server). Conversion happens inside
# the start functions where errors are handled gracefully.
_DEFAULT_HOST = os.environ.get("ARGUS_METRICS_HOST", "127.0.0.1")
_DEFAULT_PORT_STR = os.environ.get("ARGUS_METRICS_PORT", "9090")

# Sentinel for server start time — set once when the server thread begins.
_start_time: float = 0.0


class _MetricsHandler(BaseHTTPRequestHandler):
    """HTTP request handler for /health and /metrics endpoints.

    Uses the singleton MCPServer (via get_mcp_server()) to collect
    tool execution stats and session counts.
    """

    # Silence per-request log lines — too noisy for a health endpoint.
    # The parent class logs "GET /health HTTP/1.1" 200 - for every request.
    # We override log_message to suppress these in normal operation.
    # Set ARGUS_METRICS_VERBOSE=1 to restore per-request logging.
    def log_message(self, format: str, *args: Any) -> None:
        if os.environ.get("ARGUS_METRICS_VERBOSE", "").lower() in ("1", "true"):
            super().log_message(format, *args)

    @staticmethod
    def _check_llm_available() -> bool:
        """Check if the LLM client is configured and reachable.

        Uses a lazy import inside the method to avoid circular imports
        at module level. Returns False on any error (no LLM configured,
        transient network issue, etc.) — the health endpoint should
        never throw from the LLM check.
        """
        try:
            from llm_client import LLMClient
            return LLMClient().is_available()
        except Exception:
            return False

    def _send_json(self, data: dict, status: int = 200) -> None:
        """Serialize *data* as JSON and write the HTTP response."""
        body = json.dumps(data, indent=2, default=str).encode("utf-8") + b"\n"
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._handle_health()
        elif self.path == "/metrics":
            self._handle_metrics()
        else:
            self._send_json({"error": "Not found"}, 404)

    # ── /health endpoint ────────────────────────────────────────────

    @staticmethod
    def _check_celery_worker() -> dict[str, Any]:
        """Ping the Celery worker via the health ping task.

        Calls ``ping_task.run()`` directly (not through the broker) to verify
        the worker process can execute tasks. Returns the ping result dict on
        success, or an error dict on failure.
        """
        try:
            from celery_app import ping_task
            return {"alive": True, "result": ping_task.run()}
        except Exception as e:
            return {"alive": False, "error": str(e)}

    def _collect_liveness(self) -> dict[str, Any]:
        """Gather the lightweight liveness snapshot used by /health."""
        from mcp_server import get_mcp_server

        server = get_mcp_server()
        uptime = _time.time() - _start_time if _start_time > 0 else 0.0

        # Count enabled vs disabled tools via public API
        tools_list = server.get_tools()
        tools_total = len(server._tools)  # all registered (incl. disabled)
        tools_enabled = len(tools_list)   # only enabled via public API

        llm_available = self._check_llm_available()
        celery = self._check_celery_worker()

        # Determine overall status
        status = "ok"
        if tools_enabled == 0:
            status = "degraded"
        if not llm_available:
            status = "degraded"
        if not celery["alive"]:
            status = "degraded"

        return {
            "status": status,
            "uptime_seconds": round(uptime, 1),
            "llm_available": llm_available,
            "celery_worker": celery,
            "tools": {
                "total": tools_total,
                "available": tools_enabled,
                "disabled": tools_total - tools_enabled,
            },
            "sessions": {
                "active": len(server.session_store._sessions),
            },
        }

    def _handle_health(self) -> None:
        data = self._collect_liveness()
        http_status = 200 if data["status"] == "ok" else 503
        self._send_json(data, http_status)

    # ── /metrics endpoint ────────────────────────────────────────────

    def _collect_metrics(self) -> dict[str, Any]:
        """Gather the detailed metrics snapshot used by /metrics."""
        from mcp_server import get_mcp_server

        server = get_mcp_server()
        uptime = _time.time() - _start_time if _start_time > 0 else 0.0

        # Tool statistics via public API
        tools_list = server.get_tools()
        tools_total = len(server._tools)
        tools_enabled = len(tools_list)
        stats = server.get_stats()

        # Aggregate totals
        total_calls = sum(s["calls"] for s in stats.values())
        total_successes = sum(s["successes"] for s in stats.values())
        total_failures = sum(s["failures"] for s in stats.values())
        total_duration_ms = sum(s["total_duration_ms"] for s in stats.values())

        # Per-tool breakdown (limit to tools with >0 calls to keep response concise)
        tool_stats = {}
        for name, s in sorted(stats.items()):
            if s["calls"] > 0:
                tool_stats[name] = {
                    "calls": s["calls"],
                    "successes": s["successes"],
                    "failures": s["failures"],
                    "total_duration_ms": s["total_duration_ms"],
                }

        llm_available = self._check_llm_available()

        # Determine overall status
        status = "ok"
        if tools_enabled == 0:
            status = "degraded"
        if not llm_available:
            status = "degraded"
        elif total_calls > 0 and total_failures / total_calls > 0.5:
            status = "degraded"

        # Connection pool metrics (best-effort)
        pool_metrics: dict[str, Any] = {
            "available": False,
        }
        try:
            from database.connection import get_db

            db = get_db()
            pool_metrics = db.get_pool_metrics() if hasattr(db, "get_pool_metrics") else {}
            pool_metrics["available"] = True
        except Exception:
            pass

        # System info
        system_info = {
            "python_version": sys.version.split()[0],
            "platform": sys.platform,
        }

        return {
            "status": status,
            "uptime_seconds": round(uptime, 1),
            "llm_available": llm_available,
            "tools": {
                "total": tools_total,
                "available": tools_enabled,
                "disabled": tools_total - tools_enabled,
            },
            "tool_stats": tool_stats,
            "totals": {
                "calls": total_calls,
                "successes": total_successes,
                "failures": total_failures,
                "success_rate": round(total_successes / total_calls, 3) if total_calls > 0 else 0.0,
                "total_duration_ms": total_duration_ms,
            },
            "sessions": {
                "active": len(server.session_store._sessions),
            },
            "connection_pool": pool_metrics,
            "system": system_info,
        }

    def _handle_metrics(self) -> None:
        data = self._collect_metrics()
        http_status = 200 if data["status"] == "ok" else 503
        self._send_json(data, http_status)


def start_health_server(
    host: str = _DEFAULT_HOST,
    port: int = 0,  # 0 = use _DEFAULT_PORT_STR
) -> threading.Thread:
    """Start the health/metrics HTTP server on a daemon thread.

    The server listens on *host*:*port* and serves /health and /metrics.
    The thread is a daemon so it does not prevent process shutdown — the
    transport's ``run()`` loop is the primary lifecycle.

    Returns:
        The background thread (``.daemon = True``). The thread is already
        started when this function returns.

    Raises:
        OSError: If the address is already in use or otherwise unavailable.
    """
    global _start_time
    _start_time = _time.time()

    # Resolve port from param or default string
    if port == 0:
        try:
            port = int(_DEFAULT_PORT_STR)
        except (ValueError, TypeError):
            port = 9090
    port = max(1, min(port, 65535))

    # Use ThreadingHTTPServer so concurrent /health and /metrics requests
    # don't queue. For a 30s Docker probe interval this doesn't matter much,
    # but it's a one-line change for peace of mind.
    server = ThreadingHTTPServer((host, port), _MetricsHandler)
    server.timeout = 1.0  # wake every second to check for shutdown

    def _serve() -> None:
        logger.info(
            "Health server listening on http://%s:%d/health",
            host,
            port,
        )
        try:
            server.serve_forever()
        except Exception:
            logger.warning("Health server stopped: %s", exc_info=True)

    t = threading.Thread(target=_serve, daemon=True, name="health-server")
    t.start()
    return t


def start_health_server_from_env() -> threading.Thread | None:
    """Convenience wrapper that reads config from env vars.

    Reads ``ARGUS_METRICS_PORT`` and ``ARGUS_METRICS_HOST`` from the
    environment and starts the health server. If ``ARGUS_METRICS_PORT``
    is set to an empty string or ``0``, the server is **not** started
    (opting out).

    Returns:
        The background thread, or ``None`` if metrics are disabled.
    """
    raw_port = os.environ.get("ARGUS_METRICS_PORT", _DEFAULT_PORT_STR)
    if raw_port == "" or raw_port == "0":
        logger.info("Health server disabled (ARGUS_METRICS_PORT=%r)", raw_port)
        return None

    try:
        port = int(raw_port)
    except (ValueError, TypeError):
        logger.warning(
            "Invalid ARGUS_METRICS_PORT=%r — using default 9090",
            raw_port,
        )
        port = 9090

    # Clamp to valid range
    port = max(1, min(port, 65535))

    host = os.environ.get("ARGUS_METRICS_HOST", _DEFAULT_HOST)
    try:
        return start_health_server(host=host, port=port)
    except OSError as exc:
        logger.warning(
            "Health server failed to bind to %s:%d — metrics unavailable: %s",
            host,
            port,
            exc,
        )
        return None
