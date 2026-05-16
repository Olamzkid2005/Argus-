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
    """Prevent SSRF: only allow http/https URLs, block file://, internal IPs."""
    import ipaddress as _ipaddress
    import re as _re
    from urllib.parse import urlparse as _urlparse

    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Blocked non-HTTP URL (SSRF prevention): {url[:80]}")

    parsed = _urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"Could not parse hostname from URL: {url[:80]}")

    # Resolve hostname to IP and check it's not internal (prevents DNS rebinding)
    try:
        import socket as _socket
        resolved_ip = _socket.gethostbyname(hostname)
        ip = _ipaddress.ip_address(resolved_ip)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
            raise ValueError(
                f"Blocked internal IP (resolved {hostname} → {resolved_ip}): {url[:80]}"
            )
        # Block cloud metadata endpoint
        if resolved_ip == "169.254.169.254":
            raise ValueError(
                f"Blocked cloud metadata endpoint ({hostname} → {resolved_ip})"
            )
    except _socket.gaierror as e:
        raise ValueError(f"DNS resolution failed for {hostname}: {url[:80]}") from e
    except ValueError:
        raise  # re-raise our own ValueError

    # Static block for common internal patterns (belt and suspenders)
    blocked = _re.compile(
        r"(127\.0\.0\.1|localhost|0\.0\.0\.0|10\.|172\.(1[6-9]|2[0-9]|3[01])\."
        r"|192\.168\.|169\.254\.|::1|fc00:|fe80:|metadata\.google\.internal)",
        _re.IGNORECASE,
    )
    if blocked.search(hostname):
        raise ValueError(f"Blocked internal hostname (SSRF prevention): {hostname}")
    return url


def scan(target_url: str, tech_stack: list) -> list[dict]:
    slog = ScanLogger("browser_scan_worker")
    findings = []
    browser = None
    target_url = _validate_url(target_url)  # SSRF guard
    slog.tool_start("browser_scan", target=target_url)
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            console_errors = []
            page.on('console', lambda msg: console_errors.append(msg.text) if msg.type == 'error' else None)
            page.goto(target_url, timeout=30000, wait_until='networkidle')
            for payload in ['<img src=x onerror=alert(1)>', 'javascript:alert(1)']:
                pre_test_count = len(console_errors)
                payload_url = f'{target_url}?q={payload}'
                if not payload_url.startswith(("http://", "https://")):
                    continue
                page.goto(payload_url, timeout=10000)
                # Only check errors that appeared AFTER this payload navigation
                new_errors = console_errors[pre_test_count:]
                if any('alert' in e.lower() for e in new_errors):
                    findings.append({
                        'type': 'DOM_XSS',
                        'severity': 'HIGH',
                        'endpoint': target_url,
                        'evidence': {'payload': payload},
                        'source_tool': 'browser_scanner',
                        'confidence': 0.9,
                    })
        except Exception as e:
            slog.warn(f"Browser scan failed: {e}")
            logger.warning(f"Browser scan failed: {e}")
        finally:
            if browser:
                with contextlib.suppress(Exception):
                    browser.close()
    slog.tool_complete("browser_scan", findings=len(findings))
    return findings


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(json.dumps([]), file=sys.stderr)
        sys.exit(1)
    target = sys.argv[1]
    tech_stack = json.loads(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else []
    results = scan(target, tech_stack)
    print(json.dumps(results))
