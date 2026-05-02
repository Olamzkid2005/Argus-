"""
Network-level checks: host header injection, cache poisoning, HTTP request smuggling.
"""
import logging

from config.constants import RATE_LIMIT_DELAY_MS, SSL_TIMEOUT

from ._helpers import make_finding, safe_request

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = SSL_TIMEOUT
_DEFAULT_RATE_LIMIT = RATE_LIMIT_DELAY_MS / 1000.0

HOST_INJECTION = [
    "evil.com",
    "attacker.com",
    "127.0.0.1",
    "localhost",
]

CACHE_POISONING_HEADERS = {
    "X-Forwarded-For": "127.0.0.1",
    "X-Original-Forwarded-For": "127.0.0.1",
}


def run_check(target_url: str, session, findings: list) -> list[dict]:
    _check_host_header_injection(target_url, session, findings)
    _check_cache_poisoning(target_url, session, findings)
    _check_http_request_smuggling(target_url, session, findings)
    return findings


def _check_host_header_injection(target_url, session, findings):
    for host in HOST_INJECTION:
        resp = safe_request("GET", target_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT,
                            headers={"Host": host})
        if not resp:
            continue
        if host.lower() in resp.text.lower():
            findings.append(make_finding("HOST_HEADER_INJECTION", "HIGH", target_url, {
                "injected_host": host,
                "reflected_in_response": True,
            }, 0.75))
            break
        location = resp.headers.get("Location", "")
        if host.lower() in location.lower():
            findings.append(make_finding("HOST_HEADER_INJECTION", "HIGH", target_url, {
                "injected_host": host,
                "redirect_to": location,
            }, 0.8))
            break


def _check_cache_poisoning(target_url, session, findings):
    resp = safe_request("GET", target_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT,
                        headers=CACHE_POISONING_HEADERS)
    if not resp:
        return
    cache_control = resp.headers.get("Cache-Control", "")
    expires = resp.headers.get("Expires", "")
    if not cache_control and not expires:
        return
    if "127.0.0.1" in resp.text:
        findings.append(make_finding("CACHE_POISONING", "MEDIUM", target_url, {
            "headers_sent": CACHE_POISONING_HEADERS,
            "response_preview": resp.text[:200],
            "message": "Cacheable response includes poisoned headers",
        }, 0.7))


def _check_http_request_smuggling(target_url, session, findings):
    cl_te_headers = {"Content-Length": "6", "Transfer-Encoding": "chunked"}
    resp = safe_request("POST", target_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT,
                        headers=cl_te_headers, data="0\r\n\r\n")
    if resp and resp.status_code in (400, 500, 502, 504):
        findings.append(make_finding("HTTP_REQUEST_SMUGGLING_CL_TE", "HIGH", target_url, {
            "technique": "CL.TE",
            "status_code": resp.status_code,
            "message": "Potential CL.TE desync detected",
        }, 0.6))

    te_cl_headers = {"Transfer-Encoding": "chunked", "Content-Length": "6"}
    resp = safe_request("POST", target_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT,
                        headers=te_cl_headers, data="0\r\n\r\n")
    if resp and resp.status_code in (400, 500, 502, 504):
        findings.append(make_finding("HTTP_REQUEST_SMUGGLING_TE_CL", "HIGH", target_url, {
            "technique": "TE.CL",
            "status_code": resp.status_code,
            "message": "Potential TE.CL desync detected",
        }, 0.6))


class NetworkCheck:
    def __init__(self):
        self.name = "network"

    def check(self, target_url: str, session, findings: list) -> list[dict]:
        return run_check(target_url, session, findings)
