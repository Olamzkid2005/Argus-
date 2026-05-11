#!/usr/bin/env python3
"""Standalone browser scan worker — runs Playwright in its own process."""
import json
import sys

from playwright.sync_api import sync_playwright


def _validate_url(url: str) -> str:
    """Prevent SSRF: only allow http/https URLs, block file://, internal IPs."""
    import re as _re
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Blocked non-HTTP URL (SSRF prevention): {url[:80]}")
    # Block common internal addresses
    blocked = _re.compile(
        r"(127\.0\.0\.1|localhost|0\.0\.0\.0|10\.|172\.(1[6-9]|2[0-9]|3[01])|192\.168\.|169\.254\.|::1|fc00:|fe80:)", 
        _re.IGNORECASE,
    )
    if blocked.search(url):
        raise ValueError(f"Blocked internal URL (SSRF prevention): {url[:80]}")
    return url


def scan(target_url: str, tech_stack: list) -> list[dict]:
    findings = []
    browser = None
    target_url = _validate_url(target_url)  # SSRF guard
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
            import logging
            logging.getLogger(__name__).warning(f"Browser scan failed: {e}")
        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
    return findings


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(json.dumps([]), file=sys.stderr)
        sys.exit(1)
    target = sys.argv[1]
    tech_stack = json.loads(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else []
    results = scan(target, tech_stack)
    print(json.dumps(results))
