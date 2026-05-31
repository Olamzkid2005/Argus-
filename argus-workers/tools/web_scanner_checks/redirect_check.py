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

EXTERNAL_TEST_URL = "https://evil.com"


def _check_open_redirect(target_url: str, session, findings: list) -> None:
    resp = safe_request("GET", target_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
    if not resp or not resp.text:
        return
    # Find redirect-like parameters in forms and links
    param_pattern = re.compile(r'[?&](' + '|'.join(REDIRECT_PARAMS) + r')=([^&\s"\']+)', re.I)
    for match in param_pattern.finditer(resp.text):
        param_name = match.group(1)
        _ = match.group(2)  # existing value (unused, future use)
        test_url = target_url + ("&" if "?" in target_url else "?")
        test_url += f"{param_name}={EXTERNAL_TEST_URL}"
        redirect_resp = safe_request(
            "GET", test_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT,
            allow_redirects=False,
        )
        if redirect_resp is None:
            continue
        location = redirect_resp.headers.get("Location", "")
        if not location:
            continue
        if "evil.com" in location:
            findings.append(make_finding("OPEN_REDIRECT", "MEDIUM", target_url, {
                "parameter": param_name,
                "redirects_to": location,
                "test_value": EXTERNAL_TEST_URL,
            }, 0.8))
            break


def run_check(target_url: str, session, findings: list) -> list[dict]:
    return RedirectCheck().check(target_url, session, findings)


class RedirectCheck:
    def __init__(self):
        self.name = "redirect"

    def check(self, target_url: str, session, findings: list) -> list[dict]:
        _check_open_redirect(target_url, session, findings)
        return findings
