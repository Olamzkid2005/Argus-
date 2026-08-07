"""Phase: session_analysis — _activate_session_analysis and _session_analysis_tools."""

from __future__ import annotations

import logging

from ._types import ToolTask, _get_attr

logger = logging.getLogger(__name__)




# ── Phase: Session Analysis ────────────────────────────────────────────


def _activate_session_analysis(rc) -> tuple[bool, str]:
    """Activate when auth exists and session mechanisms are worth testing.

    Follows auth_testing — if the target has login or JWT, session tokens
    are worth analyzing.
    """
    has_login = _get_attr(rc, "has_login_page", False)
    auth_eps = _get_attr(rc, "auth_endpoints", [])
    has_api = _get_attr(rc, "has_api", False)
    if has_login or (auth_eps and len(auth_eps) > 0):
        return True, "auth present — session tokens should be analyzed"
    if has_api:
        return True, "API present — session/token mechanisms may exist"
    return False, "no auth context detected"


def _session_analysis_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for session token analysis."""
    return [
        ToolTask(
            tool_name="jwt_tool",
            description="JWT token analysis and manipulation",
            priority=10,
            timeout=120,
            args_template=["{target}", "-C", "-d"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="Session-related vulnerability scanning",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "session,cookie,csrf"],
        ),
    ]
