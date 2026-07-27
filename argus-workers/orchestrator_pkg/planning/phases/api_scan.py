"""Phase: api_scan — _activate_api_scan and _api_scan_tools."""

from __future__ import annotations

import logging
from typing import Any

from ._types import ToolTask, _get_attr, _get_tech_stack

logger = logging.getLogger(__name__)




# ── Phase: API Security Testing ────────────────────────────────────────

def _activate_api_scan(rc) -> tuple[bool, str]:
    """Activate when API endpoints are detected."""
    has_api = _get_attr(rc, "has_api", False)
    api_eps = _get_attr(rc, "api_endpoints", [])
    if has_api:
        return True, "API flag detected in recon"
    if api_eps and len(api_eps) > 0:
        return True, f"{len(api_eps)} API endpoint(s) discovered"
    return False, "no API endpoints detected"


def _api_scan_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for deep API security testing."""
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="nuclei",
            description="API vulnerability scanning (REST, GraphQL)",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "api,graphql,swagger,openapi,rest"],
        ),
        ToolTask(
            tool_name="arjun",
            description="API parameter discovery",
            priority=20,
            timeout=180,
            args_template=["-u", "{target}", "-m", "GET", "-t", "20"],
        ),
    ]
    # XSS scanning on API endpoints
    tools.append(ToolTask(
        tool_name="dalfox",
        description="XSS scanning on API parameters",
        priority=30,
        timeout=300,
        args_template=["url", "{target}", "--json"],
    ))
    return tools
