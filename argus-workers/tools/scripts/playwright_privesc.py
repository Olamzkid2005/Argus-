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


def check_privesc(target: str, low_priv: dict, admin_paths: list[str]) -> list[dict]:
    findings = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        page = context.new_page()
        page.goto(f"{target}/login")
        page.wait_for_load_state("networkidle")
        page.fill("input[name=username]", low_priv["username"])
        page.fill("input[name=password]", low_priv["password"])
        page.click("button[type=submit]")
        page.wait_for_load_state("networkidle")

        if not _check_auth_success(page, target):
            browser.close()
            return findings

        for path in admin_paths:
            response = page.goto(f"{target}{path}")
            if response.status == 200:
                findings.append({
                    "title": "Privilege Escalation: Unauthorized Admin Access",
                    "severity": 4,
                    "confidence": 5,
                    "description": f"Low-privilege user accessed {path} (HTTP {response.status})",
                    "tool": "playwright-privesc",
                    "evidence": [{
                        "type": "http",
                        "content": f"GET {path} -> {response.status}",
                    }],
                })

        browser.close()
    return findings


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument("--creds-file", required=True,
                        help="Path to JSON file with low-privilege credentials")
    parser.add_argument("--admin-paths", default=",".join(DEFAULT_ADMIN_PATHS))
    args = parser.parse_args()

    with open(args.creds_file) as f:
        creds = json.load(f)

    admin_paths = [p.strip() for p in args.admin_paths.split(",") if p.strip()]

    findings = check_privesc(
        args.target,
        creds,
        admin_paths,
    )
    for f in findings:
        print(json.dumps(f))

    if not findings:
        print(json.dumps({
            "title": "No Privilege Escalation vulnerability detected",
            "severity": 0,
            "confidence": 5,
            "tool": "playwright-privesc",
        }))
