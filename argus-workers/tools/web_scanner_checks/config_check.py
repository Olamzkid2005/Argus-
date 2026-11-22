"""
Security configuration checks: headers, CSP, cookies, CORS.
"""

import logging
from http.cookies import SimpleCookie

from config.constants import RATE_LIMIT_DELAY_MS, SSL_TIMEOUT

from ._helpers import make_finding, safe_request

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = SSL_TIMEOUT
_DEFAULT_RATE_LIMIT = RATE_LIMIT_DELAY_MS / 1000.0

#: Header -> severity of its absence. Capped at LOW: a missing header is not a
#: MEDIUM vulnerability by itself. X-XSS-Protection is obsolete and CSP is
#: scored by _check_csp, so neither is demanded here. Kept in sync with
#: web_scanner.py and headers_check.py.
SECURITY_HEADERS = {
    "Strict-Transport-Security": "LOW",
    "X-Frame-Options": "LOW",
    "X-Content-Type-Options": "LOW",
    "Referrer-Policy": "LOW",
    "Permissions-Policy": "LOW",
}

HEADER_FINDING_TYPES = {
    "Strict-Transport-Security": "MISSING_HSTS",
    "X-Frame-Options": "MISSING_X_FRAME_OPTIONS",
    "X-Content-Type-Options": "MISSING_X_CONTENT_TYPE_OPTIONS",
    "Referrer-Policy": "MISSING_REFERRER_POLICY",
    "Permissions-Policy": "MISSING_PERMISSIONS_POLICY",
}


def run_check(target_url: str, session, findings: list) -> list[dict]:
    return ConfigCheck().check(target_url, session, findings)


def _check_security_headers(target_url, session, findings):
    resp = safe_request(
        "GET", target_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT
    )
    if not resp:
        return
    headers = {k.lower(): v for k, v in resp.headers.items()}
    present = [h for h in SECURITY_HEADERS if h.lower() in headers]
    for header, severity in SECURITY_HEADERS.items():
        if header.lower() in headers:
            continue
        findings.append(
            make_finding(
                HEADER_FINDING_TYPES[header],
                severity,
                target_url,
                {
                    "header": header,
                    "missing_headers": [header],
                    "present_headers": present,
                    "message": f"{header} is not set on this response",
                },
                0.95,
            )
        )


def _check_csp(target_url, session, findings):
    resp = safe_request(
        "GET", target_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT
    )
    if not resp:
        return
    csp = resp.headers.get("Content-Security-Policy", "")
    if not csp:
        findings.append(
            make_finding(
                "MISSING_CSP",
                "MEDIUM",
                target_url,
                {
                    "message": "No Content-Security-Policy header found",
                },
                0.95,
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
                "WEAK_CSP",
                "MEDIUM",
                target_url,
                {
                    "unsafe_directives": unsafe,
                    "csp_preview": csp[:200],
                },
                0.9,
            )
        )


def _check_cookies(target_url, session, findings):
    resp = safe_request(
        "GET", target_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT
    )
    if not resp:
        return
    # Responses may contain multiple Set-Cookie headers; requests exposes them
    # as a comma-separated string. SimpleCookie correctly handles commas inside
    # the Expires attribute, which naive split(",") does not (H2-03).
    cookie_header = resp.headers.get("Set-Cookie")
    if not cookie_header:
        return
    cookies = SimpleCookie()
    try:
        cookies.load(cookie_header)
    except Exception:
        logger.debug("Failed to parse Set-Cookie header", exc_info=True)
        return
    for name, morsel in cookies.items():
        issues = []
        if not morsel.get("httponly"):
            issues.append("Missing HttpOnly")
        if not morsel.get("secure"):
            issues.append("Missing Secure")
        if not morsel.get("samesite"):
            issues.append("Missing SameSite")
        if issues:
            findings.append(
                make_finding(
                    "INSECURE_COOKIE",
                    "MEDIUM",
                    target_url,
                    {
                        "cookie": name,
                        "issues": issues,
                    },
                    0.9,
                )
            )


def _check_cors(target_url, session, findings):
    resp = safe_request(
        "GET",
        target_url,
        session,
        _DEFAULT_TIMEOUT,
        _DEFAULT_RATE_LIMIT,
        headers={"Origin": "http://evil.com"},
    )
    if not resp:
        return
    acao = resp.headers.get("Access-Control-Allow-Origin", "")
    acac = resp.headers.get("Access-Control-Allow-Credentials", "")
    if acao == "*":
        findings.append(
            make_finding(
                "WILDCARD_CORS",
                "HIGH",
                target_url,
                {
                    "Access-Control-Allow-Origin": "*",
                    "message": "Wildcard CORS allows any origin",
                },
                0.9,
            )
        )
    elif acao == "http://evil.com":
        acac_str = str(acac) if acac is not None else ""
        severity = "CRITICAL" if acac_str.lower() == "true" else "HIGH"
        findings.append(
            make_finding(
                "REFLECTED_ORIGIN_CORS",
                severity,
                target_url,
                {
                    "Access-Control-Allow-Origin": acao,
                    "Access-Control-Allow-Credentials": acac,
                    "message": "Server reflected evil.com origin",
                },
                0.9,
            )
        )


class ConfigCheck:
    def __init__(self):
        self.name = "config"

    def check(self, target_url: str, session, findings: list) -> list[dict]:
        _check_security_headers(target_url, session, findings)
        _check_csp(target_url, session, findings)
        _check_cookies(target_url, session, findings)
        _check_cors(target_url, session, findings)
        return findings
