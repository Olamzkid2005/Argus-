#!/usr/bin/env python3
"""Standalone browser scan worker — runs Playwright in its own process."""

import contextlib
import json
import logging
import os
import sys

from playwright.sync_api import sync_playwright

from tools import browser_scope
from tools.browser_scope import SCOPE_ENV_VAR, BrowserScopePayload, parse_scope_payload
from utils.logging_utils import ScanLogger

logger = logging.getLogger(__name__)


def _validate_url(url: str) -> str:
    """Prevent SSRF: delegate to the consolidated ScopeValidator SSOT.

    Uses ``ScopeValidator.validate_url_scheme()`` for http/https enforcement
    and ``ScopeValidator.is_internal_address()`` for private IP / cloud metadata
    blocking — the canonical implementation shared across the codebase.

    In addition, performs a DNS reachability check: if the hostname does not
    resolve, the URL is blocked. This prevents non-resolving hostnames from
    reaching Playwright, which would hang or leak DNS queries.
    """
    import socket as _socket
    from urllib.parse import urlparse as _urlparse

    from tools.scope_validator import ScopeValidator

    # 1. Scheme validation (must be http/https) — captures return for consistency
    url = ScopeValidator.validate_url_scheme(url)

    # 2. Hostname extraction
    parsed = _urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"Could not parse hostname from URL: {url[:80]}")

    # 3. DNS reachability check + capture resolved IP
    #    (browser-specific — non-resolving hostnames would cause Playwright
    #    to hang or leak DNS queries)
    try:
        resolved_ip = _socket.gethostbyname(hostname)
    except _socket.gaierror as e:
        raise ValueError(
            f"DNS resolution failed for {hostname}: {url[:80]}"
        ) from e

    # 4. Internal/SSRF target check (pass resolved_ip to avoid double DNS lookup)
    if ScopeValidator.is_internal_address(hostname, resolved_ip=resolved_ip):
        raise ValueError(
            f"Blocked internal/SSRF target (hostname resolves to internal IP): {url[:80]}"
        )

    return url


def scan(
    target_url: str, tech_stack: list, scope: BrowserScopePayload | None = None
) -> list[dict]:
    """Scan the target in a browser, bounded by the run's authorization.

    ``scope`` is the authorization the parent passed (``ARGUS_BROWSER_SCOPE``).
    Every URL this process navigates to, and every request the page makes on its
    own (subresources, XHR, iframes, redirect hops), is decided by
    ``browser_scope.request_authorized``. With no scope the target's own origin
    is the only origin reachable, so the worker never authorizes itself.
    """
    slog = ScanLogger("browser_scan_worker")
    findings: list[dict] = []
    browser = None
    try:
        target_url = _validate_url(target_url)  # SSRF guard
    except ValueError as ve:
        slog.warn("URL validation failed: %s", ve)
        return findings

    # The subprocess had no authorization of its own before this: it scanned
    # whatever URL it was handed. The top-level URL is now checked against the
    # run scope the parent passed, not against the URL's own shape.
    if not browser_scope.navigation_authorized(target_url, target_url, scope):
        slog.warn("Target %s is outside the run's browser scope", target_url)
        return findings
    if scope is not None and scope.configured:
        slog.info(
            "Browser scope: mode=%s allowed=%d blocked=%d",
            scope.mode,
            len(scope.allowed_targets),
            len(scope.blocked_targets),
        )

    slog.tool_start("browser_scan", target=target_url)
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page()

            def on_route(route, request):
                url = request.url
                if not url.lower().startswith(("http://", "https://")):
                    route.continue_()
                    return
                if browser_scope.request_authorized(url, target_url, scope):
                    route.continue_()
                    return
                slog.warn("Blocked out-of-scope browser request: %s", url)
                logger.warning("Blocked out-of-scope browser request: %s", url)
                route.abort("blockedbyclient")

            page.route("**/*", on_route)
            # Use a fresh list per payload to avoid TOCTOU race between
            # collecting errors and checking them (M7 fix)
            page.goto(target_url, timeout=30000, wait_until="networkidle")
            # Register listener once — rebind the collector list per payload (H-18)
            current_errors = []

            def on_console(msg):
                if msg.type == "error":
                    current_errors.append(msg.text)

            page.on("console", on_console)
            for payload in ["<img src=x onerror=alert(1)>", "javascript:alert(1)"]:
                current_errors = []
                payload_url = f"{target_url}?q={payload}"
                if not browser_scope.navigation_authorized(
                    payload_url, target_url, scope
                ):
                    continue
                page.goto(payload_url, timeout=10000)
                if any("alert" in e.lower() for e in current_errors):
                    findings.append(
                        {
                            "type": "DOM_XSS",
                            "severity": "HIGH",
                            "endpoint": target_url,
                            "evidence": {"payload": payload},
                            "source_tool": "browser_scanner",
                            "confidence": 0.9,
                        }
                    )
        except Exception as e:
            slog.warn("Browser scan failed: %s", e)
            logger.warning("Browser scan failed: %s", e)
        finally:
            if browser:
                with contextlib.suppress(Exception):
                    browser.close()
    slog.tool_complete("browser_scan", findings=len(findings))
    return findings


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps([]), file=sys.stderr)
        sys.exit(1)
    target = sys.argv[1]
    tech_stack = json.loads(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else []
    scope = parse_scope_payload(os.environ.get(SCOPE_ENV_VAR))
    results = scan(target, tech_stack, scope)
    print(json.dumps(results))
