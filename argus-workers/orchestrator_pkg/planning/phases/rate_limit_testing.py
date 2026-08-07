"""Phase: rate_limit_testing — _activate_rate_limit_testing and _rate_limit_testing_tools."""

from __future__ import annotations

import logging

from ._types import ToolTask, _get_attr

logger = logging.getLogger(__name__)




# ── Phase: Rate Limit Testing ────────────────────────────────────────────


def _activate_rate_limit_testing(rc) -> tuple[bool, str]:
    """Activate when rate-limit-able endpoints are detected.

    Rate limiting is a critical defense against brute-force attacks,
    credential stuffing, and API abuse. Activates when:
      - Auth endpoints exist (login, password reset, MFA)
      - API endpoints are present
      - Login page detected
    """
    has_login = _get_attr(rc, "has_login_page", False)
    auth_eps = _get_attr(rc, "auth_endpoints", [])
    has_api = _get_attr(rc, "has_api", False)
    api_eps = _get_attr(rc, "api_endpoints", [])

    reasons = []
    if has_login:
        reasons.append("login page detected")
    if auth_eps and len(auth_eps) > 0:
        reasons.append(f"{len(auth_eps)} auth endpoint(s)")
    if has_api:
        reasons.append("API present")
    if api_eps and len(api_eps) > 0:
        reasons.append(f"{len(api_eps)} API endpoint(s)")

    if reasons:
        return True, "; ".join(reasons)
    return False, "no rate-limit-able endpoints detected"


def _rate_limit_testing_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for rate limit testing.

    Probes for:
      - Login endpoint rate limiting (brute-force protection)
      - Password reset rate limiting
      - API endpoint rate limiting
      - Registration/MFA endpoint rate limiting
      - IP-based vs user-based rate limiting detection
    """
    return [
        ToolTask(
            tool_name="nuclei",
            description="Rate limit and brute-force protection scanning (login, password reset)",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "rate-limit,bruteforce,excessive"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="API rate limiting and abuse detection",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "api,rate,limit,abuse,exhaustion"],
        ),
    ]
