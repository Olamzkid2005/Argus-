#!/usr/bin/env python3
"""Standalone browser scan worker — runs Playwright in its own process."""
import sys, json
from playwright.sync_api import sync_playwright


def scan(target_url: str, tech_stack: list) -> list[dict]:
    findings = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        console_errors = []
        page.on('console', lambda msg: console_errors.append(msg.text) if msg.type == 'error' else None)
        page.goto(target_url, timeout=30000, wait_until='networkidle')
        for payload in ['<img src=x onerror=alert(1)>', 'javascript:alert(1)']:
            page.goto(f'{target_url}?q={payload}', timeout=10000)
            if any('alert' in e.lower() for e in console_errors):
                findings.append({
                    'type': 'DOM_XSS',
                    'severity': 'HIGH',
                    'endpoint': target_url,
                    'evidence': {'payload': payload},
                    'source_tool': 'browser_scanner',
                    'confidence': 0.9,
                })
        browser.close()
    return findings


if __name__ == '__main__':
    target, tech_json = sys.argv[1], sys.argv[2]
    results = scan(target, json.loads(tech_json))
    print(json.dumps(results))
