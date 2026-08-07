"""Phase: websocket_testing — _activate_websocket_testing and _websocket_testing_tools."""

from __future__ import annotations

import logging

from ._types import ToolTask, _get_attr, _get_tech_stack

logger = logging.getLogger(__name__)




# ── Phase: WebSocket Testing ────────────────────────────────────────────


def _activate_websocket_testing(rc) -> tuple[bool, str]:
    """Activate when WebSocket endpoints or signals are detected in recon.

    WebSocket connections bypass standard HTTP security controls
    (CORS, CSRF tokens, same-origin policy) and require dedicated
    testing for:
      - Origin validation bypass
      - Authentication weaknesses
      - Message injection (SQLi, NoSQLi, command injection)
      - Rate limiting absence
      - Cross-site WebSocket hijacking (CSWSH)

    Activates when:
      - ``has_websocket`` flag is set on ReconContext (forward-compatible)
      - ``websocket_endpoints`` list is populated
      - WebSocket-related keywords appear in tech_stack
      - API endpoints are present (WS often accompanies REST APIs)
    """
    # Forward-compatible: check for dedicated WebSocket attribute
    has_ws = _get_attr(rc, "has_websocket", False)
    if has_ws:
        return True, "WebSocket endpoints detected in recon"

    ws_endpoints = _get_attr(rc, "websocket_endpoints", [])
    if ws_endpoints and len(ws_endpoints) > 0:
        return True, f"{len(ws_endpoints)} WebSocket endpoint(s) found"

    # Check tech_stack for WebSocket-related keywords
    tech = _get_tech_stack(rc)
    if tech:
        tech_lower = " ".join(t.lower() for t in tech)
        ws_keywords = {"websocket", "socket.io", "socketio", "socket-io",
                       "ws://", "wss://", "signalr", "actioncable",
                       "laravel-websockets", "django channels", "flask-socketio"}
        matched = [kw for kw in ws_keywords if kw in tech_lower]
        if matched:
            return True, f"WebSocket-relevant tech detected: {', '.join(matched)}"

    # API endpoints often accompany WebSocket connections
    has_api = _get_attr(rc, "has_api", False)
    api_eps = _get_attr(rc, "api_endpoints", [])
    if has_api:
        return True, "API detected — WebSocket connections may be present"
    if api_eps and len(api_eps) > 0:
        return True, f"{len(api_eps)} API endpoint(s) — WebSocket testing recommended"

    return False, "no WebSocket signals detected"


def _websocket_testing_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for WebSocket security testing.

    Tests for:
      - Origin validation bypass (CSWSH)
      - Authentication weaknesses on WS upgrade
      - Message-level injection (SQLi, NoSQLi, command injection)
      - Rate limiting absence on WS messages
      - Sensitive data exposure via WS
      - WebSocket URL discovery via page crawling
    """
    return [
        ToolTask(
            tool_name="nuclei",
            description="WebSocket origin validation and CSWSH scanning",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "websocket,ws,origin,cswsh,hijack"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="WebSocket authentication and injection scanning",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "websocket,auth,injection,exposure"],
        ),
    ]
