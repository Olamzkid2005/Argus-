#!/usr/bin/env python3
"""Privilege Escalation detection via Playwright. Called as a subprocess by MCP server."""

import argparse
import json

from playwright.sync_api import sync_playwright

DEFAULT_ADMIN_PATHS = [
    "/admin",
    "/api/admin/users",
    "/admin/dashboard",
    "/api/users",
    "/admin/settings",
]


def _check_auth_success(page, target: str) -> bool:
    """Verify authentication succeeded by checking we're not redirected to login."""
    current = page.url
    return "/login" not in current.lower()


def check_privesc(
    target: str,
    low_priv: dict,
    admin_paths: list[str],
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
        page.fill(username_selector, low_priv["username"])
        page.fill(password_selector, low_priv["password"])
        page.click(submit_selector)
        page.wait_for_load_state("networkidle")

        if not _check_auth_success(page, target):
            browser.close()
            return findings

        for path in admin_paths:
            response = page.goto(f"{target}{path}", timeout=30000, wait_until="networkidle")
            if response.status == 200:
                findings.append(
                    {
                        "title": "Privilege Escalation: Unauthorized Admin Access",
                        "severity": 4,
                        "confidence": 5,
                        "description": f"Low-privilege user accessed {path} (HTTP {response.status})",
                        "tool": "playwright-privesc",
                        "evidence": [
                            {
                                "type": "http",
                                "content": f"GET {path} -> {response.status}",
                            }
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
        help="Path to JSON file with low-privilege credentials",
    )
    parser.add_argument(
        "--low-priv-username", default=None, help="Low-privilege user username"
    )
    parser.add_argument(
        "--low-priv-password", default=None, help="Low-privilege user password"
    )
    parser.add_argument("--admin-paths", default=",".join(DEFAULT_ADMIN_PATHS))
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
            creds = json.load(f)
    elif args.low_priv_username and args.low_priv_password:
        creds = {"username": args.low_priv_username, "password": args.low_priv_password}
    else:
        parser.error(
            "Either --creds-file or --low-priv-username/--low-priv-password must be provided"
        )

    admin_paths = [p.strip() for p in args.admin_paths.split(",") if p.strip()]

    findings = check_privesc(
        args.target,
        creds,
        admin_paths,
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
                    "title": "No Privilege Escalation vulnerability detected",
                    "severity": 0,
                    "confidence": 5,
                    "tool": "playwright-privesc",
                }
            )
        )
