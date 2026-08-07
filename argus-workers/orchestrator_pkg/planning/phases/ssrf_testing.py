"""Phase: ssrf_testing — _activate_ssrf_testing and _ssrf_testing_tools."""

from __future__ import annotations

import logging

from ._types import ToolTask, _get_attr, _get_tech_stack

logger = logging.getLogger(__name__)




# ── Phase: SSRF Testing ────────────────────────────────────────────────

def _activate_ssrf_testing(rc) -> tuple[bool, str]:
    """Activate when SSRF-prone patterns are detected in recon.

    Server-Side Request Forgery (SSRF) allows an attacker to make the
    server send requests to internal or external resources. Activates when:
      - ``has_ssrf`` flag is set on ReconContext (forward-compatible)
      - ``ssrf_signals`` list is populated
      - Parameter-bearing URLs are present (SSRF often uses URL params)
      - File upload detected (SSRF via uploaded file URLs)
      - Tech stack includes HTTP client libraries (curl, guzzle, requests)
    """
    # Forward-compatible: check for dedicated SSRF attribute
    has_ssrf = _get_attr(rc, "has_ssrf", False)
    if has_ssrf:
        return True, "SSRF signals detected in recon"

    ssrf_signals = _get_attr(rc, "ssrf_signals", [])
    if ssrf_signals and len(ssrf_signals) > 0:
        return True, f"{len(ssrf_signals)} SSRF indicator(s) found"

    # Check tech_stack for SSRF-prone technologies
    tech = _get_tech_stack(rc)
    if tech:
        tech_lower = " ".join(t.lower() for t in tech)
        ssrf_keywords = {"ssrf", "curl", "guzzle", "requests", "httpx",
                         "file_get_contents", "allow_url_fopen",
                         "fetch", "axios", "httpclient", "webclient"}
        matched = [kw for kw in ssrf_keywords if kw in tech_lower]
        if matched:
            return True, f"SSRF-relevant tech detected: {', '.join(matched)}"

    # Parameter-bearing URLs are a common SSRF vector
    param_urls = _get_attr(rc, "parameter_bearing_urls", [])
    if param_urls and len(param_urls) > 0:
        return True, f"{len(param_urls)} parameter-bearing URL(s) — SSRF vector potential"

    # File upload can involve SSRF via URL-based file sources
    has_upload = _get_attr(rc, "has_file_upload", False)
    if has_upload:
        return True, "file upload present — SSRF via URL-based file sources"

    return False, "no SSRF signals detected"


def _ssrf_testing_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for SSRF vulnerability testing.

    Tests for:
      - Blind SSRF via parameter injection
      - Timeout-based SSRF detection
      - Cloud metadata endpoint probing via SSRF
      - Internal network scanning via SSRF
      - URL-based file inclusion SSRF
      - DNS-based SSRF out-of-band detection
    """
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="nuclei",
            description="SSRF vulnerability scanning (blind, time-based, OOB)",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "ssrf,blind-oob,oast,http-injection"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="Internal network probing via SSRF (metadata, internal services)",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "ssrf,internal,metadata,network"],
        ),
    ]
    return tools
