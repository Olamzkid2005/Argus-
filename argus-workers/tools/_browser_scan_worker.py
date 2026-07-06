#!/usr/bin/env python3
"""Standalone browser scan worker — runs Playwright in its own process."""

import contextlib
import json
import logging
import sys

from playwright.sync_api import sync_playwright

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

    from tools.scope_validator import ScopeValidator
    from urllib.parse import urlparse as _urlparse

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


def scan(target_url: str, tech_stack: list) -> list[dict]:
    slog = ScanLogger("browser_scan_worker")
    findings = []
    browser = None
    try:
        target_url = _validate_url(target_url)  # SSRF guard
    except ValueError as ve:
        slog.warn("URL validation failed: %s", ve)
        return findings
    slog.tool_start("browser_scan", target=target_url)
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page()
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
                if not payload_url.startswith(("http://", "https://")):
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
    results = scan(target, tech_stack)
    print(json.dumps(results))
