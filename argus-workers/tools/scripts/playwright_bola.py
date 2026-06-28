#!/usr/bin/env python3
"""BOLA detection via Playwright. Called as a subprocess by MCP server."""

import argparse
import json

from playwright.sync_api import sync_playwright


def _check_auth_success(page, target: str) -> bool:
    """Verify authentication succeeded by checking we're not redirected to login."""
    current = page.url
    return "/login" not in current.lower()


def check_bola(
    target: str,
    attacker: dict,
    victim: dict,
    resource_pattern: str = "/api/users/{username}/details",
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
        page.fill(username_selector, attacker["username"])
        page.fill(password_selector, attacker["password"])
        page.click(submit_selector)
        page.wait_for_load_state("networkidle")

        if not _check_auth_success(page, target):
            browser.close()
            return findings

        resource_url = f"{target}{resource_pattern.format(username=victim['username'])}"
        response = page.goto(resource_url, timeout=30000, wait_until="networkidle")
        if response.status == 200:
            try:
                body = response.json()
            except Exception:
                body = response.text()
            findings.append(
                {
                    "title": "BOLA: Unauthorized Access to Victim Resource",
                    "severity": 4,
                    "confidence": 5,
                    "description": f"Attacker accessed {victim['username']}'s details without authorization",
                    "tool": "playwright-bola",
                    "evidence": [
                        {
                            "type": "http",
                            "content": json.dumps(body, indent=2)
                            if isinstance(body, dict)
                            else body,
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
        help="Path to JSON file with attacker/victim credentials",
    )
    parser.add_argument(
        "--attacker-username", default=None, help="Attacker username"
    )
    parser.add_argument(
        "--attacker-password", default=None, help="Attacker password"
    )
    parser.add_argument("--victim-username", default=None, help="Victim username")
    parser.add_argument("--victim-password", default=None, help="Victim password")
    parser.add_argument(
        "--resource-pattern",
        default="/api/users/{username}/details",
        help="URL pattern for victim resource (use {username} placeholder)",
    )
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
    elif (
        args.attacker_username
        and args.attacker_password
        and args.victim_username
        and args.victim_password
    ):
        creds = {
            "attacker": {
                "username": args.attacker_username,
                "password": args.attacker_password,
            },
            "victim": {
                "username": args.victim_username,
                "password": args.victim_password,
            },
        }
    else:
        parser.error(
            "Either --creds-file or --attacker-username/--attacker-password"
            " and --victim-username/--victim-password must be provided"
        )

    findings = check_bola(
        args.target,
        creds["attacker"],
        creds["victim"],
        args.resource_pattern,
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
                    "title": "No BOLA vulnerability detected",
                    "severity": 0,
                    "confidence": 5,
                    "tool": "playwright-bola",
                }
            )
        )
