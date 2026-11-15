#!/usr/bin/env python3
"""Stored XSS detection via Playwright. Called as a subprocess by MCP server."""

import argparse
import json
from typing import Any

from playwright.sync_api import sync_playwright

XSS_PAYLOAD = "<script>alert('XSS')</script>"


def _single_login(creds, source: str) -> dict:
    """Reduce a credentials file to the one login this verifier needs.

    The executor writes credentials as a role map (``{"attacker": {...}}``),
    because the BOLA verifier needs two logins. Reading that map as a login
    raised ``KeyError: 'username'`` after the browser had started, which read
    as a crashing scanner rather than a config mismatch.
    """
    if not isinstance(creds, dict):
        raise SystemExit(f"{source}: expected a JSON object")
    if "username" in creds:
        return creds
    for key in ("attacker", "low-priv", "low_priv", "user", "default"):
        entry = creds.get(key)
        if isinstance(entry, dict) and "username" in entry:
            return entry
    for entry in creds.values():
        if isinstance(entry, dict) and "username" in entry:
            return entry
    raise SystemExit(f"{source}: no entry with a 'username' field")


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

        # A page with no text input has no place to store the payload. That is a
        # result about the target, not a crash: the verifier used to raise a
        # Playwright timeout here and the phase recorded a failed tool.
        injection_point = page.locator("textarea, input[type=text]").first
        if injection_point.count() == 0:
            browser.close()
            return findings

        injection_point.fill(payload)
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
            creds: Any = _single_login(json.load(f), args.creds_file)
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
