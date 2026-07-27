"""Phase: access_control — _activate_access_control and _access_control_tools."""

from __future__ import annotations

import logging
from typing import Any

from ._types import ToolTask, _get_attr, _get_tech_stack

logger = logging.getLogger(__name__)




# ── Phase: Access Control Testing ──────────────────────────────────────


def _activate_access_control(rc) -> tuple[bool, str]:
    """Activate when there are authenticated endpoints or parameter-bearing URLs.

    This tests for IDOR, privilege escalation, and broken access control.
    """
    auth_eps = _get_attr(rc, "auth_endpoints", [])
    param_urls = _get_attr(rc, "parameter_bearing_urls", [])
    has_api = _get_attr(rc, "has_api", False)
    reasons = []
    if auth_eps and len(auth_eps) > 0:
        reasons.append(f"{len(auth_eps)} auth endpoint(s)")
    if param_urls and len(param_urls) > 0:
        reasons.append(f"{len(param_urls)} parameter URL(s)")
    if has_api:
        reasons.append("API detected")
    if reasons:
        return True, "; ".join(reasons)
    return False, "no authenticated or parameterized endpoints detected"


def _access_control_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for access control testing."""
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="nuclei",
            description="IDOR and broken access control scanning",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "idor,privesc,acl,exposure"],
        ),
    ]
    param_urls = _get_attr(recon_context, "parameter_bearing_urls", [])
    if param_urls and len(param_urls) > 0:
        tools.append(ToolTask(
            tool_name="arjun",
            description="Parameter discovery on IDOR-prone endpoints",
            priority=20,
            timeout=180,
            args_template=["-u", "{target}", "-m", "GET", "-t", "20"],
        ))
    return tools
