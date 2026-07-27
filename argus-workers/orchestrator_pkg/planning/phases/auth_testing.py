"""Phase: auth_testing — _activate_auth_testing and _auth_testing_tools."""

from __future__ import annotations

import logging
from typing import Any

from ._types import ToolTask, _get_attr, _get_tech_stack

logger = logging.getLogger(__name__)




# ── Phase: Authentication Testing ──────────────────────────────────────


def _activate_auth_testing(rc) -> tuple[bool, str]:
    """Activate when a login page or auth endpoints are present."""
    has_login = _get_attr(rc, "has_login_page", False)
    auth_eps = _get_attr(rc, "auth_endpoints", [])
    if has_login:
        return True, "login page detected"
    if auth_eps and len(auth_eps) > 0:
        return True, f"{len(auth_eps)} auth endpoint(s) found"
    return False, "no login page or auth endpoints detected"


def _auth_testing_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for authentication testing."""
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="nuclei",
            description="Authentication vulnerability scanning",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "auth,login,jwt,oauth,session"],
        ),
    ]
    # JWT-specific testing if JWT keywords found
    tech = _get_tech_stack(recon_context)
    if any("jwt" in t.lower() for t in tech):
        tools.append(ToolTask(
            tool_name="jwt_tool",
            description="JWT token analysis",
            priority=20,
            timeout=120,
            args_template=["{target}", "-C", "-d"],
        ))
    # Default login testing
    tools.append(ToolTask(
        tool_name="nuclei",
        description="Default credential and brute-force testing",
        priority=30,
        timeout=300,
        args_template=["-u", "{target}", "-jsonl", "-silent",
                       "-severity", "medium,high,critical",
                       "-tags", "default-login,bruteforce"],
    ))
    return tools
