"""
Authentication manager for web scanning sessions.

Handles credential-based login, cookie injection, token-based auth,
OAuth/SSO/SAML, and headless browser authentication via Playwright
so all subsequent scanner requests carry the authenticated context.
"""

import json
import logging
from dataclasses import dataclass
from urllib.parse import urljoin

import requests
from requests.exceptions import ConnectionError, RequestException, Timeout

from utils.logging_utils import ScanLogger

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
    api_key: str = ""
    api_key_header: str = "X-API-Key"

    # Headless browser auth (Playwright)
    browser_auth: bool = False

    # OAuth 2.0 fields
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    oauth_token_url: str = ""
    oauth_scope: str = ""

    # SAML assertion
    saml_assertion: str = ""


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

# Common CSRF token field names in login forms
CSRF_TOKEN_FIELDS = [
    "csrf_token",
    "csrf",
    "_csrf",
    "csrfmiddlewaretoken",
    "authenticity_token",
    "__csrf",
    "csrf-token",
    "xsrf-token",
    "_token",
    "token",
    "csrfKey",
    "csrf_param",
]


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
        3. API key header if api_key provided.
        4. Form-based or JSON login if username/password provided.
        5. OAuth 2.0 client credentials if oauth_token_url provided.
        6. SAML assertion if saml_assertion provided.
        7. Headless browser auth if browser_auth=True or form login failed
           and login_url is configured.
        """
        slog = ScanLogger("auth_manager")
        session = requests.Session()

        if self._config.cookie:
            slog.info("Injecting pre-existing cookie into session")
            for pair in self._config.cookie.split(";"):
                pair = pair.strip()
                if "=" in pair:
                    key, value = pair.split("=", 1)
                    session.cookies.set(key.strip(), value.strip())
            return session

        if self._config.token:
            slog.info("Setting %s header with Bearer token", self._config.token_header)
            session.headers[self._config.token_header] = f"Bearer {self._config.token}"
            return session

        if self._config.api_key:
            slog.info("Setting %s header with API key", self._config.api_key_header)
            session.headers[self._config.api_key_header] = self._config.api_key
            return session

        if self._config.username and self._config.password:
            try:
                return self._login(session, target_url, auth_endpoints, slog)
            except AuthError:
                if self._config.login_url and not self._config.browser_auth:
                    logger.debug(
                        "Form login failed; no browser_auth fallback configured"
                    )
                    raise

        # OAuth 2.0 client credentials
        if self._config.oauth_token_url:
            slog.info("Authenticating via OAuth 2.0 client credentials")
            return self._oauth_login(session, target_url)

        # SAML assertion
        if self._config.saml_assertion:
            slog.info("Authenticating via SAML assertion")
            return self._saml_login(session, target_url)

        # Headless browser auth — explicit request or fallback from failed form login
        if self._config.browser_auth or (
            self._config.login_url and self._config.username
        ):
            slog.info("Authenticating via headless browser (Playwright)")
            return self.browser_authenticate(target_url)

        slog.info("No credentials provided; returning unauthenticated session")
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
            session.headers[self._config.token_header] = f"Bearer {self._config.token}"

        if self._config.api_key:
            session.headers[self._config.api_key_header] = self._config.api_key

        return session

    # ------------------------------------------------------------------
    # OAuth 2.0 / SSO / SAML
    # ------------------------------------------------------------------

    def _oauth_login(
        self, session: requests.Session, target_url: str
    ) -> requests.Session:
        """Authenticate via OAuth 2.0 client credentials grant.

        POSTs to oauth_token_url with client_id, client_secret, and scope,
        then sets the returned access_token as a Bearer header on the session.
        """
        if not self._config.oauth_token_url:
            raise AuthError("OAuth token URL not configured")

        try:
            payload = {
                "grant_type": "client_credentials",
                "client_id": self._config.oauth_client_id,
                "client_secret": self._config.oauth_client_secret,
            }
            if self._config.oauth_scope:
                payload["scope"] = self._config.oauth_scope

            resp = session.post(
                self._config.oauth_token_url,
                data=payload,
                timeout=30,
                headers={"Accept": "application/json"},
            )

            if resp.status_code not in (200, 201):
                raise AuthError(
                    f"OAuth token endpoint returned {resp.status_code} "
                    f"at {self._config.oauth_token_url}"
                )

            body = resp.json()
            access_token = body.get("access_token")
            if not access_token:
                raise AuthError("OAuth response did not contain 'access_token'")

            session.headers["Authorization"] = f"Bearer {access_token}"
            logger.debug("OAuth 2.0 authentication succeeded")
            return session

        except (ConnectionError, Timeout) as exc:
            raise AuthError(
                f"Connection error during OAuth login at {self._config.oauth_token_url}: {exc}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise AuthError(
                f"OAuth token endpoint returned non-JSON response: {exc}"
            ) from exc
        except RequestException as exc:
            raise AuthError(f"Request failed during OAuth login: {exc}") from exc

    def _saml_login(
        self, session: requests.Session, target_url: str
    ) -> requests.Session:
        """Authenticate via SAML assertion.

        POSTs the SAML assertion to target_url (ACS endpoint) and captures
        any cookies or tokens from the response.
        """
        if not self._config.saml_assertion:
            raise AuthError("SAML assertion not configured")

        try:
            pre_cookies = dict(session.cookies)

            resp = session.post(
                target_url,
                data={"SAMLResponse": self._config.saml_assertion},
                timeout=30,
            )

            new_cookies = dict(session.cookies)
            if new_cookies and new_cookies != pre_cookies:
                logger.debug("SAML auth: session cookies captured from %s", target_url)
                return session

            # Fallback: try extracting token from response body
            for key in ("token", "access_token", "session_token"):
                val = self._extract_from_body(resp, key)
                if val:
                    session.headers["Authorization"] = f"Bearer {val}"
                    logger.debug("SAML auth: extracted %s from response body", key)
                    return session

            if resp.ok:
                logger.debug(
                    "SAML auth: POST succeeded but no session cookies/tokens found"
                )
                return session

            if resp.status_code in (401, 403):
                raise AuthError(
                    f"SAML assertion rejected at {target_url} with status {resp.status_code}"
                )

            raise AuthError(
                f"SAML assertion POST to {target_url} returned {resp.status_code}"
            )

        except (ConnectionError, Timeout) as exc:
            raise AuthError(
                f"Connection error during SAML login at {target_url}: {exc}"
            ) from exc
        except RequestException as exc:
            raise AuthError(f"Request failed during SAML login: {exc}") from exc

    # ------------------------------------------------------------------
    # Headless browser auth (Playwright)
    # ------------------------------------------------------------------

    def browser_authenticate(self, target_url: str) -> requests.Session:
        """Authenticate via headless browser using Playwright.

        Launches a headless Chromium, navigates to the login URL,
        fills username/password fields, submits the form, waits for
        navigation to complete, then extracts cookies and localStorage
        tokens into a requests.Session.

        Has a 60-second timeout for the whole flow.
        """
        from playwright.sync_api import sync_playwright

        login_url = self._config.login_url or target_url
        login_url = self._validate_url(login_url)

        slog = ScanLogger("auth_manager")
        slog.info("Browser auth: launching headless Chromium for %s", login_url)

        browser = None
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                page = browser.new_page()

                # Navigate to login page
                page.goto(login_url, timeout=30000, wait_until="networkidle")

                # Fill credentials from config
                username_fields = ["username", "email", "login", "user", "user_login"]
                password_fields = ["password", "passwd", "pass", "user_pass"]

                filled_username = False
                filled_password = False

                if self._config.username:
                    for selector in username_fields:
                        try:
                            page.fill(
                                f'[name="{selector}"]',
                                self._config.username,
                                timeout=5000,
                            )
                            filled_username = True
                            logger.debug(
                                "Browser auth: filled username field '%s'", selector
                            )
                            break
                        except Exception as exc:
                            # M-04: Log unexpected errors (e.g. page navigation crashes, detached elements)
                            # Expected TimeoutErrors are normal — multiple selectors are tried.
                            logger.log(
                                5,
                                "Browser auth: username field '%s' failed: %s",
                                selector,
                                exc,
                            )
                            continue
                    if not filled_username:
                        logger.debug(
                            "Browser auth: could not find username field with common selectors"
                        )

                if self._config.password:
                    for selector in password_fields:
                        try:
                            page.fill(
                                f'[name="{selector}"]',
                                self._config.password,
                                timeout=5000,
                            )
                            filled_password = True
                            logger.debug(
                                "Browser auth: filled password field '%s'", selector
                            )
                            break
                        except Exception as exc:
                            logger.log(
                                5,
                                "Browser auth: password field '%s' failed: %s",
                                selector,
                                exc,
                            )
                            continue
                    if not filled_password:
                        logger.debug(
                            "Browser auth: could not find password field with common selectors"
                        )

                # For login_data, submit custom payload fields
                if self._config.login_data and isinstance(
                    self._config.login_data, dict
                ):
                    for field_name, field_value in self._config.login_data.items():
                        if (
                            field_name.lower() in username_fields
                            or field_name.lower() in password_fields
                        ):
                            continue
                        try:
                            page.fill(
                                f'[name="{field_name}"]', str(field_value), timeout=5000
                            )
                            logger.debug(
                                "Browser auth: filled custom field '%s'", field_name
                            )
                        except Exception as exc:
                            logger.log(
                                5,
                                "Browser auth: custom field '%s' failed: %s",
                                field_name,
                                exc,
                            )
                            continue

                # Submit form via button click or Enter key
                submit_selectors = [
                    'button[type="submit"]',
                    'input[type="submit"]',
                    'button:has-text("Sign in")',
                    'button:has-text("Login")',
                    'button:has-text("Log in")',
                    'button:has-text("Sign In")',
                ]

                submitted = False
                for selector in submit_selectors:
                    try:
                        page.click(selector, timeout=5000)
                        submitted = True
                        logger.debug("Browser auth: clicked submit '%s'", selector)
                        break
                    except Exception as exc:
                        logger.log(
                            5, "Browser auth: submit '%s' failed: %s", selector, exc
                        )
                        continue

                if not submitted:
                    # Fallback: press Enter on the last filled field
                    try:
                        page.press('[name="password"]', "Enter", timeout=5000)
                        submitted = True
                    except Exception as exc:
                        logger.log(
                            5, "Browser auth: Enter key fallback failed: %s", exc
                        )
                        pass

                if not submitted:
                    raise AuthError(
                        "Browser auth: could not find submit button or submit the form"
                    )

                # Wait for post-login navigation
                page.wait_for_load_state("networkidle", timeout=30000)

                # Extract session into requests.Session
                session = self._try_extract_browser_session(page)

                slog.info("Browser auth: session extracted successfully")
                return session

        except Exception as exc:
            hint = ""
            if "playwright" in str(
                type(exc)
            ).lower() or "No module named 'playwright'" in str(exc):
                hint = " Install Playwright with: pip install playwright && python -m playwright install chromium"
            raise AuthError(f"Browser authentication failed: {exc}.{hint}") from exc
        finally:
            if browser:
                import contextlib as _cl

                with _cl.suppress(Exception):
                    browser.close()

    @staticmethod
    def _validate_url(url: str) -> str:
        """Prevent SSRF: only allow http/https URLs, block internal IPs."""
        import ipaddress as _ipaddress
        import re as _re
        import socket as _socket
        from urllib.parse import urlparse as _urlparse

        if not url.startswith(("http://", "https://")):
            raise ValueError(f"Blocked non-HTTP URL (SSRF prevention): {url[:80]}")

        parsed = _urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            raise ValueError(f"Could not parse hostname from URL: {url[:80]}")

        try:
            resolved_ip = _socket.gethostbyname(hostname)
            ip = _ipaddress.ip_address(resolved_ip)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
                raise ValueError(
                    f"Blocked internal IP (resolved {hostname} -> {resolved_ip}): {url[:80]}"
                )
            if resolved_ip == "169.254.169.254":
                raise ValueError(
                    f"Blocked cloud metadata endpoint ({hostname} -> {resolved_ip})"
                )
        except _socket.gaierror as e:
            raise ValueError(f"DNS resolution failed for {hostname}: {url[:80]}") from e

        blocked = _re.compile(
            r"(127\.0\.0\.1|localhost|0\.0\.0\.0|10\.|172\.(1[6-9]|2[0-9]|3[01])\."
            r"|192\.168\.|169\.254\.|::1|fc00:|fe80:|metadata\.google\.internal)",
            _re.IGNORECASE,
        )
        if blocked.search(hostname):
            raise ValueError(f"Blocked internal hostname (SSRF prevention): {hostname}")
        return url

    @staticmethod
    def _try_extract_browser_session(page) -> requests.Session:
        """Extract cookies and localStorage tokens from a Playwright page into a requests.Session."""
        session = requests.Session()

        # Extract cookies from browser context
        try:
            cookies = page.context().cookies()
            for c in cookies:
                session.cookies.set(c["name"], c["value"])
            logger.debug("Browser auth: extracted %d cookies", len(cookies))
        except Exception as e:
            logger.warning(
                "Browser auth: failed to extract cookies: %s — session may be incomplete",
                e,
            )

        # Extract localStorage tokens
        try:
            local_storage = page.evaluate("() => JSON.stringify(window.localStorage)")
            storage_data = json.loads(local_storage)
            token_keys = [
                "token",
                "access_token",
                "refresh_token",
                "jwt",
                "auth",
                "session",
            ]
            for key in token_keys:
                val = storage_data.get(key) or storage_data.get(f"access_{key}")
                if val:
                    session.headers["Authorization"] = f"Bearer {val}"
                    logger.debug("Browser auth: extracted %s from localStorage", key)
                    break
        except Exception as e:
            logger.warning(
                "Browser auth: no localStorage tokens found: %s — session may be incomplete",
                e,
            )

        return session

    # ------------------------------------------------------------------
    # Session validity / re-authentication
    # ------------------------------------------------------------------

    @staticmethod
    def session_valid(session: requests.Session, test_url: str) -> bool:
        """Check whether a session is still authenticated.

        Makes a GET request to test_url (or the login URL). Returns False
        if the response is 401/403 or if redirected to a login page.
        """
        LOGIN_INDICATORS = ["/login", "/signin", "sign in", "log in", "login"]

        try:
            resp = session.get(
                test_url,
                timeout=15,
                allow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; Argus/1.0)"},
            )

            if resp.status_code in (401, 403):
                return False

            # Detect redirect to login page
            final_url = resp.url.lower()
            if any(indicator in final_url for indicator in LOGIN_INDICATORS):
                return False

            # Check body for login page indicators
            body_lower = (resp.text or "").lower()
            login_body_patterns = [
                "<form",
                'name="password"',
                'name="login"',
                'type="password"',
            ]
            if resp.status_code == 200:
                matches = sum(1 for p in login_body_patterns if p in body_lower)
                if matches >= 2:
                    return False

            return True

        except (ConnectionError, Timeout, RequestException) as exc:
            logger.debug("Session validity check failed for %s: %s", test_url, exc)
            return False

    def ensure_session(
        self, session: requests.Session, target_url: str
    ) -> requests.Session:
        """Verify session is still valid; re-authenticate if needed.

        Calls session_valid() against target_url. If invalid, calls
        authenticate() to get a fresh session.
        """
        if self.session_valid(session, target_url):
            return session

        logger.warning("Session expired — re-authenticating for %s", target_url)
        return self.authenticate(target_url)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_csrf_token(
        self, login_page_url: str, session: requests.Session
    ) -> str | None:
        """Fetch the login page and extract CSRF token from hidden form fields.

        Many web applications embed a CSRF token in the login form that must
        be submitted with the credentials. This method fetches the page and
        looks for common CSRF token field names in hidden inputs.

        Args:
            login_page_url: URL of the login page to fetch
            session: Requests session to use for the GET

        Returns:
            The CSRF token value, or None if no token was found.
        """
        try:
            resp = session.get(
                login_page_url,
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0 (compatible; Argus/1.0)"},
            )
            if resp.status_code != 200:
                return None

            import re

            body = resp.text

            # Search for hidden input fields with CSRF token names
            for field_name in CSRF_TOKEN_FIELDS:
                # Pattern: <input ... name="csrf_token" ... value="abc123" ...>
                patterns = [
                    re.compile(
                        rf'<input[^>]*name=["\']{re.escape(field_name)}["\'][^>]*value=["\']([^"\']+)["\']',
                        re.IGNORECASE,
                    ),
                    re.compile(
                        rf'<input[^>]*value=["\']([^"\']+)["\'][^>]*name=["\']{re.escape(field_name)}["\']',
                        re.IGNORECASE,
                    ),
                ]
                for pat in patterns:
                    match = pat.search(body)
                    if match:
                        token = match.group(1)
                        logger.debug(
                            "Extracted CSRF token '%s' from field '%s'",
                            token[:20],
                            field_name,
                        )
                        return token

            # Also check for meta tags with CSRF tokens (common in SPAs)
            meta_patterns = [
                re.compile(
                    r'<meta[^>]*name=["\']csrf-token["\'][^>]*content=["\']([^"\']+)["\']',
                    re.IGNORECASE,
                ),
            ]
            for pat in meta_patterns:
                match = pat.search(body)
                if match:
                    token = match.group(1)
                    logger.debug("Extracted CSRF token from meta tag: '%s'", token[:20])
                    return token

            return None
        except requests.RequestException as e:
            logger.debug("Failed to fetch login page for CSRF extraction: %s", e)
            return None

    def _login(
        self,
        session: requests.Session,
        target_url: str,
        auth_endpoints: list[str] | None,
    ) -> requests.Session:
        """Try each candidate login URL until one succeeds.

        Before POSTing credentials, fetches the login page to extract
        any CSRF token that must be submitted with the form.
        """
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

            # Pre-fetch login page to extract CSRF token
            csrf_token = self._extract_csrf_token(normalized, session)
            if csrf_token:
                logger.debug("Found CSRF token for %s", normalized)

            try:
                if self._try_login(session, normalized, csrf_token):
                    logger.info("Authentication succeeded at %s", normalized)
                    return session
            except AuthError:
                logger.debug("Login failed at %s", normalized)
                continue

        raise AuthError(
            f"Authentication failed: could not log in at any endpoint "
            f"(tried {len(seen)} URLs)"
        )

    def _try_login(
        self, session: requests.Session, url: str, csrf_token: str | None = None
    ) -> bool:
        """
        Attempt a single login POST.

        Includes any extracted CSRF token in the form payload.
        Returns True if a session cookie was captured.
        """
        username = self._config.username
        password = self._config.password
        login_data = self._config.login_data

        payload = login_data or self._build_form_payload(username, password)

        # Inject CSRF token into form payload if one was extracted
        if csrf_token and isinstance(payload, dict):
            # Try to find which CSRF field name the app expects
            # First check if any CSRF field name already exists in payload
            csrf_key_found = None
            for field in CSRF_TOKEN_FIELDS:
                if field in payload:
                    csrf_key_found = field
                    break
            if not csrf_key_found:
                # Default to 'csrf_token' — apps usually accept their own field name
                payload["csrf_token"] = csrf_token

        pre_cookies = dict(session.cookies)

        headers: dict[str, str] = {}
        is_json = False

        if login_data and isinstance(login_data, dict):
            value_sample = next(iter(login_data.values()), "")
            if isinstance(value_sample, (dict, list)) or any(
                str(v).strip().startswith(("{", "[")) for v in login_data.values()
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
                logger.warning(
                    "Auth config specifies GET login method for %s — "
                    "credentials would be exposed in URL query params. "
                    "Falling back to POST for security.",
                    url,
                )
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
    def _build_form_payload(username: str, password: str) -> dict[str, str]:
        """Build a form-urlencoded payload trying common field names."""
        payload: dict[str, str] = {}
        payload[COMMON_USERNAME_FIELDS[0]] = username
        payload[COMMON_PASSWORD_FIELDS[0]] = password
        return payload

    @staticmethod
    def _extract_from_body(resp: requests.Response, key: str) -> str | None:
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
