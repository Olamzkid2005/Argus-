"""Phase: csrf_testing — _activate_csrf_testing and _csrf_testing_tools."""

from __future__ import annotations

import logging

from ._types import ToolTask, _get_attr, _get_tech_stack

logger = logging.getLogger(__name__)




# ── Phase: CSRF Testing ───────────────────────────────────────────────────


def _activate_csrf_testing(rc) -> tuple[bool, str]:
    """Activate when form endpoints or session-based auth are detected.

    Cross-Site Request Forgery (CSRF) occurs when an attacker tricks a
    user's browser into executing unwanted actions on an authenticated
    session. Any state-changing operation (POST, PUT, DELETE) without
    anti-CSRF tokens is potentially vulnerable.

    Activates when:
      - ``has_csrf`` flag is set on ReconContext (forward-compatible)
      - ``form_endpoints`` list is populated (forward-compatible)
      - Auth endpoints are present (login, registration, password reset)
      - Login page is detected
      - API endpoints are present (CSRF on APIs)
      - Session-related keywords appear in tech_stack
      - Form submissions detected in crawled paths
    """
    # Forward-compatible: check for dedicated CSRF attribute
    has_csrf = _get_attr(rc, "has_csrf", False)
    if has_csrf:
        return True, "CSRF signals detected in recon"

    form_eps = _get_attr(rc, "form_endpoints", [])
    if form_eps and len(form_eps) > 0:
        return True, f"{len(form_eps)} form endpoint(s) found"

    reasons = []

    # Auth endpoints are CSRF-prone (login, password reset, etc.)
    auth_eps = _get_attr(rc, "auth_endpoints", [])
    has_login = _get_attr(rc, "has_login_page", False)
    if auth_eps and len(auth_eps) > 0:
        reasons.append(f"{len(auth_eps)} auth endpoint(s)")
    if has_login:
        reasons.append("login page")

    # API endpoints can be vulnerable to CSRF
    has_api = _get_attr(rc, "has_api", False)
    api_eps = _get_attr(rc, "api_endpoints", [])
    if has_api:
        reasons.append("API detected")
    if api_eps and len(api_eps) > 0:
        reasons.append(f"{len(api_eps)} API endpoint(s)")

    # Check tech_stack for session/auth-related keywords
    tech = _get_tech_stack(rc)
    if tech:
        tech_lower = " ".join(t.lower() for t in tech)
        csrf_keywords = {"csrf", "csrf token", "session", "cookie",
                         "auth token", "jwt", "antiforgery",
                         "antiforgerytoken", "x-csrf-token",
                         "__requestverificationtoken"}
        matched = [kw for kw in csrf_keywords if kw in tech_lower]
        if matched:
            reasons.append(f"security tech: {', '.join(matched[:2])}")

    if reasons:
        return True, "; ".join(reasons[:3])

    return False, "no form endpoints or session-based auth detected"


def _csrf_testing_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for CSRF vulnerability testing.

    Tests for:
      - Missing CSRF tokens on state-changing endpoints (POST, PUT, DELETE)
      - Weak/guessable CSRF token generation
      - CSRF token validation bypass (referer, origin, custom header)
      - CSRF on JSON endpoints (content-type switching)
      - SameSite cookie bypass for CSRF
      - Anti-CSRF token reuse/replay
      - Anti-CSRF token leakage via referer/response headers
    """
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="nuclei",
            description="CSRF vulnerability scanning (missing tokens, weak validation, SameSite bypass)",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "csrf,samesite,cookie,exposure,bypass"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="CSRF token analysis and anti-forgery protection scanning",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "csrf,bypass,antiforgery,header,referer"],
        ),
    ]
    return tools
