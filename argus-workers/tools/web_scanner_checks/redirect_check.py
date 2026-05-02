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
    return RedirectCheck().check(target_url, session, findings)
class RedirectCheck:
    def __init__(self):
        self.name = "redirect"

    def check(self, target_url: str, session, findings: list) -> list[dict]:
        return run_check(target_url, session, findings)
