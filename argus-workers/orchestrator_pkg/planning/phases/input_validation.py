"""Phase: input_validation — _activate_input_validation and _input_validation_tools."""

from __future__ import annotations

import logging

from ._types import ToolTask, _get_attr

logger = logging.getLogger(__name__)




# ── Phase: Input Validation Testing ────────────────────────────────────


def _activate_input_validation(rc) -> tuple[bool, str]:
    """Activate when parameter-bearing URLs are present.

    Tests for XSS, SQLi, SSTI, and other injection vulnerabilities
    on discovered parameters.
    """
    param_urls = _get_attr(rc, "parameter_bearing_urls", [])
    if param_urls and len(param_urls) > 0:
        return True, f"{len(param_urls)} parameter-bearing URL(s) found"
    return False, "no parameter-bearing URLs detected"


def _input_validation_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for input validation and injection testing."""
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="dalfox",
            description="XSS scanning on input parameters",
            priority=10,
            timeout=300,
            args_template=["url", "{target}", "--json"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="Injection vulnerability scanning",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "injection,sqli,lfi,ssrf,ssti"],
        ),
    ]
    return tools
