#!/usr/bin/env python3
"""Standalone browser scan worker — runs Playwright in its own process."""
import json
import sys

from playwright.sync_api import sync_playwright


def scan(target_url: str, tech_stack: list) -> list[dict]:
    findings = []
    browser = None
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            console_errors = []
            page.on('console', lambda msg: console_errors.append(msg.text) if msg.type == 'error' else None)
            page.goto(target_url, timeout=30000, wait_until='networkidle')
            for payload in ['<img src=x onerror=alert(1)>', 'javascript:alert(1)']:
                pre_test_count = len(console_errors)
                page.goto(f'{target_url}?q={payload}', timeout=10000)
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
