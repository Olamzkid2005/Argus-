"""Tests for API-style endpoint detection in form discovery.

Covers the new detection logic in ``_scan_common_paths``:
- JSON API endpoints (Content-Type: application/json, body starts with ``{``)
- Auth keyword pages (body contains login/signin/password/username/email/token/auth)
- 405 Method Not Allowed responses
- HTML form detection still works
- ``discover_auth_endpoints`` sets ``login_mode`` correctly
"""

from __future__ import annotations

import importlib.util
import os
from typing import Any

# ── Import form_discovery without triggering agent/__init__.py ──

_spec = importlib.util.spec_from_file_location(
    "form_discovery",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "agent", "form_discovery.py"),
)
_fd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fd)


# ── Helpers ──


class _MockResponse:
    """Minimal mock for requests.Response with only the attributes we need."""

    def __init__(
        self,
        status_code: int = 200,
        text: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = {"Content-Type": "text/html", **(headers or {})}

    @property
    def ok(self) -> bool:
        """``requests.Response.ok`` is a property, not a method."""
        return 200 <= self.status_code < 400


class _MockSession:
    """Minimal mock for requests.Session that returns pre-configured responses."""

    def __init__(self, responses: list[_MockResponse]) -> None:
        self._responses = responses
        self._call_count = 0

    def get(self, url: str, **kwargs: Any) -> _MockResponse:
        if self._call_count >= len(self._responses):
            return _MockResponse(404, "Not found")
        resp = self._responses[self._call_count]
        self._call_count += 1
        return resp

    def post(self, url: str, **kwargs: Any) -> _MockResponse:
        return self.get(url, **kwargs)


# ── Tests for _scan_common_paths ──


class TestScanCommonPathsApiDetection:
    """Tests for ``_scan_common_paths`` API endpoint detection."""

    def test_html_form_detected(self) -> None:
        """HTML form with input fields (existing behavior) still works."""
        session = _MockSession([
            _MockResponse(200, '<html><form><input name="email"></form></html>'),
        ])
        result: dict[str, Any] = {}
        _fd._scan_common_paths("http://example.com", session, ["/login"], result, "login")
        assert result.get("login_url") == "http://example.com/login"

    def test_json_api_detected_via_content_type(self) -> None:
        """JSON API endpoint detected via Content-Type: application/json."""
        session = _MockSession([
            _MockResponse(
                200,
                '{"status":"ok","message":"Welcome"}',
                {"Content-Type": "application/json"},
            ),
        ])
        result: dict[str, Any] = {}
        _fd._scan_common_paths("http://example.com", session, ["/api/login"], result, "login")
        assert result.get("login_url") == "http://example.com/api/login"
        assert result.get("login_mode") == "api"

    def test_json_api_detected_via_body_start(self) -> None:
        """JSON API endpoint detected when body starts with ``{`` even without JSON Content-Type."""
        session = _MockSession([
            _MockResponse(200, '{"error":"Method not allowed"}'),
        ])
        result: dict[str, Any] = {}
        _fd._scan_common_paths("http://example.com", session, ["/api/login"], result, "login")
        assert result.get("login_url") == "http://example.com/api/login"

    def test_auth_keywords_detected(self) -> None:
        """Page with multiple auth keywords (>=2 required) is detected."""
        session = _MockSession([
            _MockResponse(200, "<html><body>Enter your email and password</body></html>"),
        ])
        result: dict[str, Any] = {}
        _fd._scan_common_paths("http://example.com", session, ["/login"], result, "login")
        assert result.get("login_url") == "http://example.com/login"

    def test_single_auth_keyword_not_enough(self) -> None:
        """A single generic keyword like 'password' alone is not enough."""
        session = _MockSession([
            _MockResponse(200, "<html><body>Enter your password</body></html>"),
        ])
        result: dict[str, Any] = {}
        _fd._scan_common_paths("http://example.com", session, ["/login"], result, "login")
        assert result.get("login_url") is None

    def test_405_detected(self) -> None:
        """405 Method Not Allowed is detected as an API-style endpoint."""
        session = _MockSession([
            _MockResponse(405, "Method Not Allowed"),
        ])
        result: dict[str, Any] = {}
        _fd._scan_common_paths("http://example.com", session, ["/api/login"], result, "login")
        assert result.get("login_url") == "http://example.com/api/login"
        assert result.get("login_mode") == "api"

    def test_plain_404_not_detected(self) -> None:
        """A plain 404 without auth keywords is NOT detected."""
        session = _MockSession([
            _MockResponse(404, "Not Found"),
        ])
        result: dict[str, Any] = {}
        _fd._scan_common_paths("http://example.com", session, ["/api/login"], result, "login")
        assert result.get("login_url") is None

    def test_404_with_auth_keywords_not_detected(self) -> None:
        """Auth keywords only trigger detection on OK responses, not 404."""
        session = _MockSession([
            _MockResponse(404, "Enter your password"),
        ])
        result: dict[str, Any] = {}
        _fd._scan_common_paths("http://example.com", session, ["/login"], result, "login")
        assert result.get("login_url") is None

    def test_first_path_wins(self) -> None:
        """The first matching path is returned — later paths are not checked."""
        session = _MockSession([
            _MockResponse(200, '{"token":"abc"}', {"Content-Type": "application/json"}),
            _MockResponse(200, '<form><input name="email"></form>'),
            _MockResponse(200, "password page"),
        ])
        result: dict[str, Any] = {}
        _fd._scan_common_paths(
            "http://example.com", session,
            ["/api/login", "/login", "/signin"], result, "login",
        )
        # Should find api/login first (JSON response)
        assert result.get("login_url") == "http://example.com/api/login"

    def test_register_paths_also_detected(self) -> None:
        """Register paths use the same detection logic."""
        session = _MockSession([
            _MockResponse(200, '{"status":"ok"}', {"Content-Type": "application/json"}),
        ])
        result: dict[str, Any] = {}
        _fd._scan_common_paths(
            "http://example.com", session,
            ["/register", "/signup"], result, "register",
        )
        assert result.get("register_url") == "http://example.com/register"
        assert result.get("register_mode") == "api"


class TestDiscoverAuthEndpointsLoginMode:
    """Tests for ``discover_auth_endpoints`` login_mode logic."""

    def test_login_mode_api_when_json_response(self) -> None:
        """login_mode is ``api`` when a JSON API endpoint is discovered."""
        session = _MockSession([
            # _scan_common_paths probes REGISTER_PATHS first — none match
            _MockResponse(404, "Not Found"),  # /register
            _MockResponse(404, "Not Found"),  # /signup
            _MockResponse(404, "Not Found"),  # /sign-up
            _MockResponse(404, "Not Found"),  # /create-account
            _MockResponse(404, "Not Found"),  # /auth/register
            _MockResponse(404, "Not Found"),  # /api/register
            _MockResponse(404, "Not Found"),  # /api/auth/register
            _MockResponse(404, "Not Found"),  # /account/create
            _MockResponse(404, "Not Found"),  # /users/new
            # _scan_common_paths probes LOGIN_PATHS — /login matches (JSON)
            _MockResponse(200, '{"token":"abc"}', {"Content-Type": "application/json"}),
            # Field extraction: GET /login again
            _MockResponse(200, '{"token":"abc"}', {"Content-Type": "application/json"}),
        ])
        result = _fd.discover_auth_endpoints("http://example.com", session)
        assert result.get("login_url") == "http://example.com/login"
        # login_fields will be empty since it's JSON, not HTML
        assert result.get("login_mode") == "api"

    def test_login_mode_api_when_no_html_fields(self) -> None:
        """login_mode is ``api`` when URL found but HTML form fields cannot be extracted."""
        session = _MockSession([
            # REGISTER_PATHS — none match
            _MockResponse(404, "Not Found"),  # /register
            _MockResponse(404, "Not Found"),  # /signup
            _MockResponse(404, "Not Found"),  # /sign-up
            _MockResponse(404, "Not Found"),  # /create-account
            _MockResponse(404, "Not Found"),  # /auth/register
            _MockResponse(404, "Not Found"),  # /api/register
            _MockResponse(404, "Not Found"),  # /api/auth/register
            _MockResponse(404, "Not Found"),  # /account/create
            _MockResponse(404, "Not Found"),  # /users/new
            # LOGIN_PATHS — /login returns 405
            _MockResponse(405, "Method Not Allowed"),
            # Field extraction: GET /login again (also 405)
            _MockResponse(405, "Method Not Allowed"),
        ])
        result = _fd.discover_auth_endpoints("http://example.com", session)
        assert result.get("login_url") == "http://example.com/login"
        assert result.get("login_mode") == "api"

    def test_login_mode_form_when_html_form_present(self) -> None:
        """login_mode stays ``form`` when HTML form fields are extracted."""
        html = """
        <html><body>
        <form method="post" action="/login">
          <input name="email" type="email">
          <input name="password" type="password">
        </form>
        </body></html>
        """
        session = _MockSession([
            # REGISTER_PATHS — none match
            _MockResponse(404, "Not Found"),  # /register
            _MockResponse(404, "Not Found"),  # /signup
            _MockResponse(404, "Not Found"),  # /sign-up
            _MockResponse(404, "Not Found"),  # /create-account
            _MockResponse(404, "Not Found"),  # /auth/register
            _MockResponse(404, "Not Found"),  # /api/register
            _MockResponse(404, "Not Found"),  # /api/auth/register
            _MockResponse(404, "Not Found"),  # /account/create
            _MockResponse(404, "Not Found"),  # /users/new
            # LOGIN_PATHS — /login matches (HTML form)
            _MockResponse(200, html),
            # Field extraction: GET /login again
            _MockResponse(200, html),
        ])
        result = _fd.discover_auth_endpoints("http://example.com", session)
        assert result.get("login_url") == "http://example.com/login"
        assert result.get("login_mode") == "form"
        assert result.get("login_fields", {}).get("email") == "email"
