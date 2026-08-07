"""Phase: open_redirect — _activate_open_redirect and _open_redirect_tools."""

from __future__ import annotations

import logging

from ._types import ToolTask, _get_attr, _get_tech_stack

logger = logging.getLogger(__name__)

# Redirect parameter patterns commonly found in URL parameters
_REDIRECT_PARAM_PATTERNS: set[str] = {
    "redirect", "redirect_url", "redirect_uri", "redirect_to",
    "url", "uri", "u", "next", "next_url", "return",
    "return_to", "return_url", "return_uri", "goto",
    "dest", "destination", "target", "continue",
    "continue_url", "forward", "forward_url",
    "href", "ref", "referrer", "link", "out",
    "view", "load", "file", "page", "document",
}


def _has_redirect_params(param_urls: list[str]) -> bool:
    """Check if any parameter-bearing URL contains redirect-like parameters.

    Examines query parameters in the URL for known redirect parameter names
    (e.g., ``redirect``, ``url``, ``next``, ``goto``, ``return``). These are
    common sinks for open redirect vulnerabilities.

    Args:
        param_urls: List of parameter-bearing URLs.

    Returns:
        True if at least one redirect parameter pattern is found.
    """
    if not param_urls:
        return False
    from urllib.parse import parse_qs, urlparse
    for url in param_urls:
        try:
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            param_names_lower = {p.lower() for p in params}
            if param_names_lower & _REDIRECT_PARAM_PATTERNS:
                return True
        except Exception:
            continue
    return False


def _count_redirect_params(param_urls: list[str]) -> int:
    """Count how many parameter-bearing URLs have redirect parameters."""
    if not param_urls:
        return 0
    from urllib.parse import parse_qs, urlparse
    count = 0
    for url in param_urls:
        try:
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            param_names_lower = {p.lower() for p in params}
            if param_names_lower & _REDIRECT_PARAM_PATTERNS:
                count += 1
        except Exception:
            continue
    return count


def _get_redirect_param_names(param_urls: list[str]) -> list[str]:
    """Get the matched redirect parameter names found in URLs."""
    if not param_urls:
        return []
    from urllib.parse import parse_qs, urlparse
    matched: set[str] = set()
    for url in param_urls:
        try:
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            param_names_lower = {p.lower() for p in params}
            matched.update(param_names_lower & _REDIRECT_PARAM_PATTERNS)
        except Exception:
            continue
    return sorted(matched)[:5]


def _activate_open_redirect(rc) -> tuple[bool, str]:
    """Activate when parameter-bearing URLs contain redirect patterns.

    Open redirect vulnerabilities allow attackers to redirect users to
    arbitrary external URLs via the target's redirect parameters.
    While often considered low-severity, open redirects are frequently
    chained with phishing campaigns and can bypass URL validation in
    SSO/OAuth flows.

    Activates when:
      - ``has_open_redirect`` flag is set on ReconContext (forward-compatible)
      - ``redirect_endpoints`` list is populated (forward-compatible)
      - Parameter-bearing URLs contain redirect-like parameter names
        (redirect, url, next, goto, return, etc.)
      - Redirect-related keywords appear in tech_stack
    """
    # Forward-compatible: check for dedicated open redirect attribute
    has_oredirect = _get_attr(rc, "has_open_redirect", False)
    if has_oredirect:
        return True, "open redirect signals detected in recon"

    redirect_eps = _get_attr(rc, "redirect_endpoints", [])
    if redirect_eps and len(redirect_eps) > 0:
        return True, f"{len(redirect_eps)} redirect endpoint(s) found"

    # Check tech_stack for redirect-related technologies
    tech = _get_tech_stack(rc)
    if tech:
        tech_lower = " ".join(t.lower() for t in tech)
        redirect_keywords = {"redirect", "forward", "rewrite",
                             "mod_rewrite", "url-rewrite", "route-redirect"}
        matched = [kw for kw in redirect_keywords if kw in tech_lower]
        if matched:
            return True, f"redirect-related tech detected: {', '.join(matched)}"

    # Parameter-bearing URLs with redirect parameter names
    param_urls = _get_attr(rc, "parameter_bearing_urls", [])
    if param_urls and _has_redirect_params(param_urls):
        redirect_count = _count_redirect_params(param_urls)
        matched_params = _get_redirect_param_names(param_urls)
        suffix = f" (params: {', '.join(matched_params)})" if matched_params else ""
        return True, f"{redirect_count} URL(s) with redirect parameters{suffix}"

    return False, "no open redirect signals detected"


def _open_redirect_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for open redirect vulnerability testing.

    Tests for:
      - Open redirect via common parameter names (redirect, url, next, goto)
      - Blind open redirect via multiple parameter injection
      - XSS chaining via redirect (javascript:/data: URIs in redirect params)
      - OAuth/SSO redirect_uri validation bypass
      - Host header injection combined with redirect parameters
    """
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="nuclei",
            description="Open redirect vulnerability scanning (common parameters)",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "redirect,open-redirect,oast,exposure"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="Open redirect chaining and parameter injection scanning",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "redirect,ssrf,oast,url-injection,parameter"],
        ),
    ]
    return tools
