#!/usr/bin/env python3
"""Stored XSS detection via Playwright. Called as a subprocess by MCP server."""

import argparse
import json
from typing import Any

from playwright.sync_api import sync_playwright

XSS_PAYLOAD = "<script>alert('XSS')</script>"


def _check_auth_success(page, target: str) -> bool:
    """Verify authentication succeeded by checking multiple signals.

    Checks:
    1. URL no longer points to a login/signin/auth page
    2. No login form elements (password field) on the current page
    3. No auth error messages in the page body
    """
    current = page.url.lower()

    # Signal 1: URL check — if we're still on a login page, auth likely failed
    still_on_login = any(
        p in current for p in ["/login", "/signin", "/auth/login", "/auth"]
    )
    if not still_on_login:
        return True

    # Signal 2: Check for auth error messages in the page
    try:
        body_text = page.text_content("body") or ""
        body_lower = body_text.lower()
        auth_errors = [
            "invalid credentials",
            "invalid username",
            "invalid password",
            "invalid email",
            "login failed",
            "incorrect",
            "wrong password",
            "authentication failed",
            "access denied",
        ]
        if any(e in body_lower for e in auth_errors):
            return False
    except Exception:
        pass

    # Signal 3: Check if there's still a password field visible (still on login form)
    try:
        password_count = page.locator("input[type=password]").count()
        if password_count > 0:
            return False  # Still on a login form
    except Exception:
        pass

    # If URL suggests login but no error or form found, it might be a redirect
    # or SPA — proceed anyway
    return True


def check_stored_xss(
    target: str,
    credentials: dict,
    form_path: str,
    payload: str,
    username_selector: str = "input[name=username]",
    password_selector: str = "input[name=password]",
    submit_selector: str = "button[type=submit]",
) -> list[dict]:
    findings: list[dict] = []
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
        "--creds-file",
        default=None,
        help="Path to JSON file with login credentials",
    )
    parser.add_argument("--username", default=None, help="Login username")
    parser.add_argument("--password", default=None, help="Login password")
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

    if args.creds_file:
        with open(args.creds_file) as f:
            creds: Any = json.load(f)
    elif args.username and args.password:
        creds = {"username": args.username, "password": args.password}
    else:
        parser.error("Either --creds-file or --username/--password must be provided")

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
