"""
Authentication security checks: default credentials, brute force detection,
session fixation, password reset analysis, and registration endpoint discovery.
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
    ("root", "root"),
    ("test", "test"),
    ("guest", "guest"),
    ("admin", "admin123"),
    ("admin", "letmein"),
    ("user", "user"),
    ("admin", "pass123"),
    ("admin", "123456"),
]

RESET_PATHS = [
    "/forgot-password",
    "/reset-password",
    "/api/auth/forgot-password",
]

REGISTER_PATHS = [
    "/signup",
    "/register",
    "/api/auth/signup",
]


def run_check(target_url: str, session, findings: list) -> list[dict]:
    return AuthCheck().check(target_url, session, findings)
def _discover_auth_endpoints(target_url: str, session) -> list[str]:
    found = []
    for path in AUTH_PATHS:
        url = urljoin(target_url, path.lstrip("/"))
        resp = safe_request("GET", url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
        if not resp or resp.status_code not in (200, 302, 401, 403):
            continue
        found.append(url)
    return found


def _check_default_credentials(target_url, session, findings):
    endpoints = _discover_auth_endpoints(target_url, session)
    for url in endpoints:
        resp = safe_request("GET", url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
        if resp and resp.status_code in (200, 302):
            findings.append(make_finding("AUTH_ENDPOINT_DISCOVERED", "INFO", url, {
                "path": url,
                "status_code": resp.status_code,
            }, 0.9))
        for username, password in DEFAULT_CREDS:
            try:
                login_resp = safe_request(
                    "POST", url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT,
                    data={"username": username, "password": password},
                    allow_redirects=False,
                )
                if not login_resp or login_resp.status_code not in (200, 302):
                    continue
                location = str(login_resp.headers.get("Location", "")).lower()
                if any(x in location for x in ["dashboard", "admin", "home", "welcome"]):
                    findings.append(make_finding("DEFAULT_CREDENTIALS", "CRITICAL", url, {
                        "username": username,
                        "password": password,
                        "redirect_to": location,
                    }, 0.9))
            except Exception:
                logger.debug("Default cred test failed for %s", url)


def _check_brute_force(target_url, session, findings):
    endpoints = _discover_auth_endpoints(target_url, session)
    for url in endpoints:
        try:
            blocked = False
            for _ in range(5):
                resp = safe_request(
                    "POST", url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT,
                    data={"username": "nonexistent_user_xyz", "password": "wrongpass"},
                    allow_redirects=False,
                )
                if resp and resp.status_code in (429, 403):
                    blocked = True
                    break
            if not blocked:
                findings.append(make_finding(
                    "WEAK_BRUTE_FORCE_PROTECTION", "HIGH", url, {
                        "attempts": 5,
                        "message": "No rate limiting or lockout detected after 5 rapid failed logins",
                    }, 0.8,
                ))
        except Exception:
            logger.debug("Brute force check failed for %s", url)


def _check_session_fixation(target_url, session, findings):
    endpoints = _discover_auth_endpoints(target_url, session)
    for url in endpoints:
        try:
            pre_resp = safe_request("GET", url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
            if not pre_resp:
                continue
            pre_cookies = {c.name: c.value for c in session.cookies}
            session_cookie_name = _find_session_cookie(pre_cookies)
            if not session_cookie_name:
                logger.debug("No session cookie found for %s, skipping session fixation check", url)
                continue
            pre_value = pre_cookies[session_cookie_name]
            safe_request(
                "POST", url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT,
                data={"username": "admin", "password": "wrong_pass_xyz"},
                allow_redirects=False,
            )
            post_cookies = {c.name: c.value for c in session.cookies}
            post_value = post_cookies.get(session_cookie_name)
            if post_value and post_value == pre_value:
                findings.append(make_finding(
                    "SESSION_FIXATION", "HIGH", url, {
                        "session_cookie": session_cookie_name,
                        "pre_auth_value": pre_value,
                        "post_auth_value": post_value,
                        "message": "Session cookie not rotated after login attempt",
                    }, 0.7,
                ))
        except Exception:
            logger.debug("Session fixation check failed for %s", url)


def _find_session_cookie(cookies: dict) -> str | None:
    session_keywords = ["session", "sid", "token", "auth", "connect.sid", "jsessionid", "phpsessid"]
    for kw in session_keywords:
        for name in cookies:
            if kw in name.lower():
                return name
    for name in cookies:
        if name.lower() in ("sessionid", "session_id", "sessid"):
            return name
    return None


def _check_password_reset(target_url, session, findings):
    for path in RESET_PATHS:
        url = urljoin(target_url, path.lstrip("/"))
        try:
            resp = safe_request("GET", url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
            if resp and resp.status_code == 200:
                findings.append(make_finding("RESET_ENDPOINT_DISCOVERED", "INFO", url, {
                    "path": path,
                    "status_code": 200,
                }, 0.9))
            for email in ["nonexistent@test.com", "admin@example.com"]:
                post_resp = safe_request(
                    "POST", url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT,
                    data={"email": email},
                    allow_redirects=False,
                )
                if not post_resp or post_resp.status_code not in (200, 302, 422):
                    continue
                body = (post_resp.text or "").lower()
                if "email not found" in body or "no account" in body or "not registered" in body:
                    findings.append(make_finding(
                        "RESET_INFO_DISCLOSURE", "MEDIUM", url, {
                            "path": path,
                            "message": "Password reset endpoint reveals whether an email exists",
                            "test_email": email,
                            "response_snippet": body[:200],
                        }, 0.8,
                    ))
                    break
        except Exception:
            logger.debug("Password reset check failed for %s", url)


def _check_registration_endpoints(target_url, session, findings):
    for path in REGISTER_PATHS:
        url = urljoin(target_url, path.lstrip("/"))
        try:
            resp = safe_request("GET", url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
            if resp and resp.status_code in (200, 302):
                findings.append(make_finding("REGISTRATION_ENDPOINT_DISCOVERED", "INFO", url, {
                    "path": path,
                    "status_code": resp.status_code,
                }, 0.9))
        except Exception:
            logger.debug("Registration endpoint check failed for %s", url)


class AuthCheck:
    def __init__(self):
        self.name = "auth"

    def check(self, target_url: str, session, findings: list) -> list[dict]:
        return run_check(target_url, session, findings)
