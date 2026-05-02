"""
Authentication endpoint discovery and default credential testing.
"""
import logging
from urllib.parse import urljoin

from config.constants import RATE_LIMIT_DELAY_MS, SSL_TIMEOUT

from ._helpers import make_finding, safe_request

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = SSL_TIMEOUT
_DEFAULT_RATE_LIMIT = RATE_LIMIT_DELAY_MS / 1000.0

AUTH_PATHS = [
    "/login", "/signin", "/auth", "/admin", "/dashboard",
    "/api/auth/login", "/api/login", "/wp-login.php",
]

DEFAULT_CREDS = [
    ("admin", "admin"),
    ("admin", "password"),
    ("admin", "123456"),
    ("admin", "admin123"),
    ("root", "root"),
    ("test", "test"),
    ("guest", "guest"),
    ("admin", "letmein"),
]


def run_check(target_url: str, session, findings: list) -> list[dict]:
    for path in AUTH_PATHS:
        url = urljoin(target_url, path.lstrip("/"))
        resp = safe_request("GET", url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
        if not resp or resp.status_code not in (200, 302):
            continue
        findings.append(make_finding("AUTH_ENDPOINT_DISCOVERED", "INFO", url, {
            "path": path,
            "status_code": resp.status_code,
        }, 0.9))
        for username, password in DEFAULT_CREDS[:3]:
            login_resp = safe_request("POST", url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT,
                                      data={"username": username, "password": password},
                                      allow_redirects=False)
            if not login_resp or login_resp.status_code not in (200, 302):
                continue
            location = str(login_resp.headers.get("Location", "")).lower()
            if any(x in location for x in ["dashboard", "admin", "home", "welcome"]):
                findings.append(make_finding("DEFAULT_CREDENTIALS", "CRITICAL", url, {
                    "username": username,
                    "password": password,
                    "redirect_to": location,
                }, 0.7))
        break
    return findings


class UauthCheck:
    def __init__(self):
        self.name = "auth"

    def check(self, target_url: str, session, findings: list) -> list[dict]:
        return run_check(target_url, session, findings)
