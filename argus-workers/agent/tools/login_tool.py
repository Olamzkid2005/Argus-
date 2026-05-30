"""
login tool — autonomous login for the LLM agent.

Discovers login forms, submits credentials, captures session cookies/JWT,
and returns an AuthContext with the authenticated session on success.
"""

from __future__ import annotations

import json
from typing import Any

import requests

from agent.auth_context import AuthContext
from tools.models import ToolResult

# ── Constants ──

MAX_RETRIES = 3

# Backoff delays (seconds) per attempt, with ±50% jitter applied at runtime.
BACKOFF_DELAYS = [5, 30, 60]


def run_login(
    target: str,
    http_session: requests.Session,
    auth_context: AuthContext | None = None,
    email: str | None = None,
    password: str | None = None,
    recon_crawled_paths: list[str] | None = None,
) -> tuple[ToolResult, AuthContext | None]:
    """Execute the login tool.

    This is a skeleton implementation for Phase 2b.
    Full form discovery and login logic will be added in Phase 6.

    Args:
        target: Base URL of the target application.
        http_session: Requests session for HTTP calls.
        auth_context: Optional existing auth context (provides stored credentials).
        email: Optional email override. Falls back to auth_context.email.
        password: Optional password override. Falls back to auth_context.password.
        recon_crawled_paths: Optional list of discovered paths from recon phase.

    Returns:
        Tuple of (ToolResult, updated AuthContext or None).
    """
    # TODO: Implement full form discovery and login logic.
    # For now, return a placeholder indicating the tool exists.
    ctx = auth_context or AuthContext()
    return (
        ToolResult(
            stdout=json.dumps({
                "status": "not_implemented",
                "message": "login tool skeleton — full implementation pending (Phase 6)",
            }),
            success=False,
            tool="login",
        ),
        ctx,
    )
