"""Phase: cors_origin_testing — _activate_cors_origin_testing and _cors_origin_testing_tools."""

from __future__ import annotations

import logging
from typing import Any

from ._types import ToolTask, _get_attr, _get_tech_stack

logger = logging.getLogger(__name__)




# ── Phase: CORS Origin Testing ────────────────────────────────────────────


def _activate_cors_origin_testing(rc) -> tuple[bool, str]:
    """Activate when CORS-related signals are detected in recon.

    CORS (Cross-Origin Resource Sharing) misconfigurations can allow
    unauthorized cross-origin data access. Activates when:
      - ``has_cors`` flag is set on ReconContext (forward-compatible)
      - CORS header keywords appear in tech_stack
      - API endpoints are present (CORS is primarily an API concern)
    """
    # Forward-compatible: check for dedicated CORS attribute
    has_cors = _get_attr(rc, "has_cors", False)
    if has_cors:
        return True, "CORS headers detected in recon"

    cors_headers = _get_attr(rc, "cors_headers", [])
    if cors_headers and len(cors_headers) > 0:
        return True, f"{len(cors_headers)} CORS header(s) found"

    # Check tech_stack for CORS-related keywords
    tech = _get_tech_stack(rc)
    if tech:
        tech_lower = " ".join(t.lower() for t in tech)
        cors_keywords = {"cors", "access-control", "rest", "restful",
                         "graphql", "api gateway", "openapi"}
        matched = [kw for kw in cors_keywords if kw in tech_lower]
        if matched:
            return True, f"CORS-relevant tech detected: {', '.join(matched)}"

    # API endpoints often involve CORS
    has_api = _get_attr(rc, "has_api", False)
    api_eps = _get_attr(rc, "api_endpoints", [])
    if has_api:
        return True, "API detected — CORS configuration should be verified"
    if api_eps and len(api_eps) > 0:
        return True, f"{len(api_eps)} API endpoint(s) — CORS misconfig likely"

    return False, "no CORS signals detected"


def _cors_origin_testing_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for CORS origin testing.

    Tests for:
      - Wildcard origin credentials misconfiguration
      - Reflected origin reflection (trusted origins list bypass)
      - Preflight request validation weaknesses
      - CORS-header injection via null/arbitrary origins
      - Cross-origin data leakage via ACAO + ACC headers
    """
    return [
        ToolTask(
            tool_name="nuclei",
            description="CORS misconfiguration scanning (wildcard, origin reflection, preflight)",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "cors,headers,misconfig,exposure"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="Cross-origin data leakage and CORS bypass scanning",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "cors,origin,access-control,leak"],
        ),
    ]
