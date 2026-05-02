"""
HTTP security headers check — missing/insecure HTTP security headers.
"""
import logging

import requests

from config.constants import RATE_LIMIT_DELAY_MS, SSL_TIMEOUT

from ._helpers import make_finding, safe_request

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = SSL_TIMEOUT
_DEFAULT_RATE_LIMIT = RATE_LIMIT_DELAY_MS / 1000.0

SECURITY_HEADERS = [
    "Strict-Transport-Security",
    "X-Frame-Options",
    "X-Content-Type-Options",
    "Referrer-Policy",
    "Permissions-Policy",
    "X-XSS-Protection",
    "Content-Security-Policy",
]


def run_check(target_url: str, session, findings: list) -> list[dict]:
    _check_security_headers(target_url, session, findings)
    _check_csp(target_url, session, findings)
    _check_cookies(target_url, session, findings)
    _check_cors(target_url, session, findings)
    return findings


def _check_security_headers(target_url, session, findings):
    resp = safe_request("GET", target_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
    if not resp:
        return
    headers = {k.lower(): v for k, v in resp.headers.items()}
    missing = []
    for header in SECURITY_HEADERS:
        if header.lower() not in headers:
            missing.append(header)
    if missing:
        findings.append(
            make_finding(
                finding_type="MISSING_SECURITY_HEADERS",
                severity="MEDIUM",
                endpoint=target_url,
                evidence={
                    "missing_headers": missing,
                    "present_headers": [
                        h for h in SECURITY_HEADERS if h.lower() in headers
                    ],
                },
                confidence=0.95,
            )
        )


def _check_csp(target_url, session, findings):
    resp = safe_request("GET", target_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
    if not resp:
        return
    csp = resp.headers.get("Content-Security-Policy", "")
    if not csp:
        findings.append(
            make_finding(
                finding_type="MISSING_CSP",
                severity="MEDIUM",
                endpoint=target_url,
                evidence={"message": "No Content-Security-Policy header found"},
                confidence=0.95,
            )
        )
        return
    unsafe = []
    if "unsafe-inline" in csp:
        unsafe.append("unsafe-inline")
    if "unsafe-eval" in csp:
        unsafe.append("unsafe-eval")
    if "*." in csp or "*:" in csp:
        unsafe.append("wildcard domains")
    if unsafe:
        findings.append(
            make_finding(
                finding_type="WEAK_CSP",
                severity="MEDIUM",
                endpoint=target_url,
                evidence={
                    "unsafe_directives": unsafe,
                    "csp_preview": csp[:200],
                },
                confidence=0.9,
            )
        )


def _check_cookies(target_url, session, findings):
    resp = safe_request("GET", target_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
    if not resp:
        return
    cookie_header = resp.headers.get("Set-Cookie")
    if not cookie_header:
        return
    cookies = cookie_header.split(",") if "," in cookie_header else [cookie_header]
    for cookie_str in cookies:
        issues = []
        if "HttpOnly" not in cookie_str:
            issues.append("Missing HttpOnly")
        if "Secure" not in cookie_str:
            issues.append("Missing Secure")
        if "SameSite" not in cookie_str:
            issues.append("Missing SameSite")
        if issues:
            cookie_name = cookie_str.split("=")[0] if "=" in cookie_str else "unknown"
            findings.append(
                make_finding(
                    finding_type="INSECURE_COOKIE",
                    severity="MEDIUM",
                    endpoint=target_url,
                    evidence={
                        "cookie": cookie_name,
                        "issues": issues,
                    },
                    confidence=0.9,
                )
            )


def _check_cors(target_url, session, findings):
    resp = safe_request(
        "GET",
        target_url,
        session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT,
        headers={"Origin": "http://evil.com"},
    )
    if not resp:
        return
    acao = resp.headers.get("Access-Control-Allow-Origin", "")
    acac = resp.headers.get("Access-Control-Allow-Credentials", "")
    if acao == "*":
        findings.append(
            make_finding(
                finding_type="WILDCARD_CORS",
                severity="HIGH",
                endpoint=target_url,
                evidence={
                    "Access-Control-Allow-Origin": "*",
                    "message": "Wildcard CORS allows any origin",
                },
                confidence=0.9,
            )
        )
    elif acao == "http://evil.com":
        acac_str = str(acac) if acac is not None else ""
        severity = "CRITICAL" if acac_str.lower() == "true" else "HIGH"
        findings.append(
            make_finding(
                finding_type="REFLECTED_ORIGIN_CORS",
                severity=severity,
                endpoint=target_url,
                evidence={
                    "Access-Control-Allow-Origin": acao,
                    "Access-Control-Allow-Credentials": acac,
                    "message": "Server reflected evil.com origin",
                },
                confidence=0.9,
            )
        )


class HeadersCheck:
    def __init__(self):
        self.name = "headers"

    def check(self, target_url: str, session, findings: list) -> list[dict]:
        return run_check(target_url, session, findings)
