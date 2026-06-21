#!/usr/bin/env python3
"""Stored XSS detection via Playwright. Called as a subprocess by MCP server."""

import argparse
import json

from playwright.sync_api import sync_playwright

XSS_PAYLOAD = "<script>alert('XSS')</script>"


def _check_auth_success(page, target: str) -> bool:
    """Verify authentication succeeded by checking we're not redirected to login."""
    current = page.url
    return "/login" not in current.lower()


def check_stored_xss(
    target: str,
    credentials: dict,
    form_path: str,
    payload: str,
    username_selector: str = "input[name=username]",
    password_selector: str = "input[name=password]",
    submit_selector: str = "button[type=submit]",
) -> list[dict]:
    findings = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context()

        page = context.new_page()
        page.goto(f"{target}/login", timeout=30000, wait_until="networkidle")
        page.fill(username_selector, credentials["username"])
        page.fill(password_selector, credentials["password"])
        page.click(submit_selector)
        page.wait_for_load_state("networkidle")

        if not _check_auth_success(page, target):
            browser.close()
            return findings

        page.goto(f"{target}{form_path}", timeout=30000, wait_until="networkidle")

        page.fill("textarea, input[type=text]", payload)
        page.click("button[type=submit]")
        page.wait_for_load_state("networkidle")

        page.goto(f"{target}", timeout=30000, wait_until="networkidle")

        content = page.content()
        if payload in content:
            findings.append(
                {
                    "title": "Stored XSS: Payload Rendered on Page",
                    "severity": 4,
                    "confidence": 5,
                    "description": f"XSS payload '{payload}' was rendered after injection",
                    "tool": "playwright-xss",
                    "evidence": [
                        {"type": "http", "content": "Payload found in page source"}
                    ],
                }
            )

        browser.close()
    return findings


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument(
        "--creds-file", required=True, help="Path to JSON file with login credentials"
    )
    parser.add_argument("--form-page", default="/feedback")
    parser.add_argument("--payload", default=XSS_PAYLOAD)
    parser.add_argument(
        "--username-selector",
        default="input[name=username]",
        help="CSS selector for username field",
    )
    parser.add_argument(
        "--password-selector",
        default="input[name=password]",
        help="CSS selector for password field",
    )
    parser.add_argument(
        "--submit-selector",
        default="button[type=submit]",
        help="CSS selector for submit button",
    )
    args = parser.parse_args()

    with open(args.creds_file) as f:
        creds = json.load(f)

    findings = check_stored_xss(
        args.target,
        creds,
        args.form_page,
        args.payload,
        args.username_selector,
        args.password_selector,
        args.submit_selector,
    )
    for f in findings:
        print(json.dumps(f))

    if not findings:
        print(
            json.dumps(
                {
                    "title": "No Stored XSS vulnerability detected",
                    "severity": 0,
                    "confidence": 5,
                    "tool": "playwright-xss",
                }
            )
        )
