"""
Open redirect parameter detection and testing.
"""
import logging
import re

from config.constants import RATE_LIMIT_DELAY_MS, SSL_TIMEOUT

from ._helpers import make_finding, safe_request

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = SSL_TIMEOUT
_DEFAULT_RATE_LIMIT = RATE_LIMIT_DELAY_MS / 1000.0

REDIRECT_PARAMS = [
    "redirect", "url", "next", "dest", "redirect_url",
    "return", "continue", "to", "ref", "dest_url", "target", "goto",
]


def run_check(target_url: str, session, findings: list) -> list[dict]:
    resp = safe_request("GET", target_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
    if not resp:
        return findings

    url_params = re.findall(r'[?&](\w+)=', resp.text)

    for param in REDIRECT_PARAMS:
        if param in url_params or param in resp.text.lower():
            test_url = f"{target_url}?{param}=http://evil.com"
            test_resp = safe_request("GET", test_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT,
                                     allow_redirects=False)
            if test_resp and test_resp.status_code in (301, 302, 303, 307, 308):
                location = test_resp.headers.get("Location", "")
                if "evil.com" in location:
                    findings.append(make_finding("OPEN_REDIRECT", "HIGH", test_url, {
                        "parameter": param,
                        "redirect_to": location,
                        "status_code": test_resp.status_code,
                    }, 0.8))

    return findings


class UredirectCheck:
    def __init__(self):
        self.name = "redirect"

    def check(self, target_url: str, session, findings: list) -> list[dict]:
        return run_check(target_url, session, findings)
