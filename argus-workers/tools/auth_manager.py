"""
Authentication manager for web scanning sessions.

Handles credential-based login, cookie injection, and token-based auth
so all subsequent scanner requests carry the authenticated context.
"""
import json
import logging
from dataclasses import dataclass
from urllib.parse import urljoin

import requests
from requests.exceptions import ConnectionError, RequestException, Timeout

logger = logging.getLogger(__name__)


class AuthError(Exception):
    """Raised when authentication fails for any reason."""


@dataclass
class AuthConfig:
    """Authentication configuration for scanning."""

    username: str = ""
    password: str = ""
    cookie: str = ""
    token: str = ""
    token_header: str = "Authorization"
    login_url: str = ""
    login_data: dict | None = None
    login_method: str = "POST"


COMMON_LOGIN_PATHS = [
    "/login",
    "/signin",
    "/auth/login",
    "/api/auth/login",
    "/api/login",
    "/auth",
]

COMMON_USERNAME_FIELDS = ["username", "email", "login", "user", "user_login"]
COMMON_PASSWORD_FIELDS = ["password", "passwd", "pass", "user_pass"]


class AuthManager:
    """
    Handles authentication for web scanning sessions.

    Usage:
        auth = AuthManager(config)
        session = auth.authenticate(target_url)
    """

    def __init__(self, auth_config: AuthConfig | dict | None = None):
        self._config = auth_config
        if isinstance(auth_config, dict):
            self._config = AuthConfig(**auth_config)
        elif auth_config is None:
            self._config = AuthConfig()

    def authenticate(
        self, target_url: str, auth_endpoints: list[str] | None = None
    ) -> requests.Session:
        """
        Perform authentication and return an authenticated requests.Session.

        Strategy
        --------
        1. Direct cookie injection if cookie string provided.
        2. Bearer / custom-header token if token string provided.
        3. Form-based or JSON login if username/password provided.
        """
        session = requests.Session()

        if self._config.cookie:
            logger.debug("Injecting pre-existing cookie into session")
            for pair in self._config.cookie.split(";"):
                pair = pair.strip()
                if "=" in pair:
                    key, value = pair.split("=", 1)
                    session.cookies.set(key.strip(), value.strip())
            return session

        if self._config.token:
            logger.debug("Setting %s header with Bearer token", self._config.token_header)
            session.headers[self._config.token_header] = (
                f"Bearer {self._config.token}"
            )
            return session

        if self._config.username and self._config.password:
            return self._login(session, target_url, auth_endpoints)

        logger.debug("No credentials provided; returning unauthenticated session")
        return session

    def attach_to_session(self, session: requests.Session) -> requests.Session:
        """Attach auth cookies/tokens to an existing session."""
        if self._config.cookie:
            for pair in self._config.cookie.split(";"):
                pair = pair.strip()
                if "=" in pair:
                    key, value = pair.split("=", 1)
                    session.cookies.set(key.strip(), value.strip())

        if self._config.token:
            session.headers[self._config.token_header] = (
                f"Bearer {self._config.token}"
            )

        return session

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _login(
        self,
        session: requests.Session,
        target_url: str,
        auth_endpoints: list[str] | None,
    ) -> requests.Session:
        """Try each candidate login URL until one succeeds."""
        candidates: list[str] = []

        if auth_endpoints:
            candidates.extend(auth_endpoints)

        candidates.extend(COMMON_LOGIN_PATHS)

        if self._config.login_url:
            candidates.append(self._config.login_url)

        seen = set()
        for path in candidates:
            normalized = urljoin(target_url.rstrip("/") + "/", path.lstrip("/"))
            if normalized in seen:
                continue
            seen.add(normalized)

            logger.debug("Attempting login at %s", normalized)
            try:
                if self._try_login(session, normalized):
                    logger.info("Authentication succeeded at %s", normalized)
                    return session
            except AuthError:
                logger.debug("Login failed at %s", normalized)
                continue

        raise AuthError(
            f"Authentication failed: could not log in at any endpoint "
            f"(tried {len(seen)} URLs)"
        )

    def _try_login(self, session: requests.Session, url: str) -> bool:
        """
        Attempt a single login POST.

        Returns True if a session cookie was captured.
        """
        username = self._config.username
        password = self._config.password
        login_data = self._config.login_data

        payload = login_data or self._build_form_payload(username, password)

        pre_cookies = dict(session.cookies)

        headers: dict[str, str] = {}
        is_json = False

        if login_data and isinstance(login_data, dict):
            value_sample = next(iter(login_data.values()), "")
            if isinstance(value_sample, (dict, list)) or any(
                str(v).strip().startswith(("{", "["))
                for v in login_data.values()
            ):
                is_json = True

        if is_json:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload)
        else:
            data = payload

        try:
            method = self._config.login_method.upper()
            if method == "GET":
                resp = session.get(url, params=data, headers=headers, timeout=30)
            else:
                resp = session.post(url, data=data, headers=headers, timeout=30)

            new_cookies = dict(session.cookies)

            if new_cookies and new_cookies != pre_cookies:
                logger.debug(
                    "Session cookies captured from %s: %s", url, set(new_cookies)
                )
                return True

            if resp.ok:
                for key in ("token", "access_token", "api_key", "sid"):
                    val = self._extract_from_body(resp, key)
                    if val:
                        session.headers["Authorization"] = f"Bearer {val}"
                        logger.debug("Extracted %s from response body at %s", key, url)
                        return True

            if resp.status_code in (401, 403):
                raise AuthError(
                    f"Server returned {resp.status_code} for login at {url}"
                )

            return False

        except (ConnectionError, Timeout) as exc:
            raise AuthError(f"Connection error during login at {url}: {exc}") from exc
        except RequestException as exc:
            raise AuthError(f"Request failed during login at {url}: {exc}") from exc

    @staticmethod
    def _build_form_payload(
        username: str, password: str
    ) -> dict[str, str]:
        """Build a form-urlencoded payload trying common field names."""
        payload: dict[str, str] = {}
        payload[COMMON_USERNAME_FIELDS[0]] = username
        payload[COMMON_PASSWORD_FIELDS[0]] = password
        return payload

    @staticmethod
    def _extract_from_body(
        resp: requests.Response, key: str
    ) -> str | None:
        """Try to extract *key* from a JSON or HTML response body."""
        ct = (resp.headers.get("Content-Type") or "").lower()
        if "json" in ct:
            try:
                body = resp.json()
                if isinstance(body, dict):
                    val = body.get(key)
                    if isinstance(val, str) and val.strip():
                        return val.strip()
                    if isinstance(nested := body.get("data"), dict):
                        val = nested.get(key)
                        if isinstance(val, str) and val.strip():
                            return val.strip()
            except (json.JSONDecodeError, ValueError):
                pass
        return None
