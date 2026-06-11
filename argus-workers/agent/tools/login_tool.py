"""
login tool — autonomous login for the LLM agent.

Discovers login forms, submits credentials, captures session cookies/JWT,
handles retries with jittered backoff, and returns an AuthContext with the
authenticated session on success.

Flow:
1. Check for credentials (provided, from AuthContext, or error)
2. Discover login endpoint (hybrid: recon data + common paths)
3. Extract form fields
4. Submit login form
5. Check response for errors (2FA, locked, invalid, rate-limited)
6. Capture session cookies + JWT tokens
7. Store AuthContext with session
"""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Any

import requests

from agent.auth_context import AuthContext
from agent.form_discovery import ERROR_CODES, discover_auth_endpoints
from tool_core.result import ToolStatus, UnifiedToolResult

logger = logging.getLogger(__name__)

# ── Constants ──

MAX_RETRIES = 10
BACKOFF_DELAYS = [1, 3, 5, 5, 10, 10, 15, 15, 30, 30]

# Cookie names that indicate a JWT/bearer token
TOKEN_COOKIE_NAMES = frozenset({
    "token", "jwt", "access_token", "authorization",
    "id_token", "refresh_token", "bearer",
})


# ── Public API ──


# ── Common API field name permutations for API-style login ──
# When no HTML form fields are available (API mode), the login tool
# iterates through these combinations to find the right field names.
_API_FIELD_PERMUTATIONS: list[tuple[str, str]] = [
    ("email", "password"),       # most common for modern APIs
    ("username", "password"),    # common for legacy systems
    ("login", "password"),       # common for some APIs
    ("email", "pass"),           # shorter variant
    ("username", "pass"),        # shorter variant
    ("email", "passwd"),         # passwd variant
    ("user", "password"),        # user/password
]


def run_login(
    target: str,
    http_session: requests.Session,
    auth_context: AuthContext | None = None,
    email: str | None = None,
    password: str | None = None,
    recon_crawled_paths: list[str] | None = None,
    login_url: str | None = None,
) -> tuple[UnifiedToolResult, AuthContext | None]:
    """Execute the login tool.

    Discovers login form → submits credentials → captures session →
    returns AuthContext.

    Supports both HTML-form-based login (discovers form fields automatically)
    and API-style login (JSON body with common field name permutations).

    Args:
        target: Base URL of the target application.
        http_session: Requests session for HTTP calls.
        auth_context: Optional existing auth context (provides stored credentials).
        email: Optional email override. Falls back to auth_context.email.
        password: Optional password override. Falls back to auth_context.password.
        recon_crawled_paths: Optional list of discovered paths from recon phase.
        login_url: Optional direct login URL override (skips discovery if provided).

    Returns:
        Tuple of (UnifiedToolResult, updated AuthContext or None).
    """
    ctx = auth_context or AuthContext()

    # Use provided credentials or fall back to stored credentials
    login_email = email or ctx.email
    login_password = password or ctx.password

    if not login_email or not login_password:
        return (
            UnifiedToolResult(
                tool_name="login",
                status=ToolStatus.NONZERO_EXIT,
                stdout=json.dumps({
                    "status": "failed",
                    "error_code": "NO_CREDENTIALS",
                    "message": (
                        "No credentials available. Call register() first "
                        "or provide email/password."
                    ),
                }),
                stderr=(
                    "No credentials available. Call register() first "
                    "or provide email/password."
                ),
            ),
            ctx,
        )

    # Discover login endpoint (or use provided login_url override)
    if login_url:
        endpoints = {
            "login_url": login_url,
            "login_fields": {},
            "login_mode": "api",
            "login_content_type": None,
        }
        logger.debug("Login: using provided login_url='%s'", login_url)
    else:
        endpoints = discover_auth_endpoints(target, http_session, recon_crawled_paths)

    login_url = endpoints.get("login_url")

    if not login_url:
        return (
            UnifiedToolResult(
                tool_name="login",
                status=ToolStatus.NONZERO_EXIT,
                stdout=json.dumps({
                    "status": "failed",
                    "error_code": "FORM_NOT_FOUND",
                    "message": ERROR_CODES["FORM_NOT_FOUND"],
                }),
                stderr=ERROR_CODES["FORM_NOT_FOUND"],
            ),
            ctx,
        )

    fields = endpoints.get("login_fields", {})
    login_mode = endpoints.get("login_mode", "form")

    last_error: str | None = None
    result_data: dict[str, Any] = {
        "status": "failed",
        "login_url": login_url,
        "attempts": 0,
        "login_mode": login_mode,
    }

    # ── Attempt login with retries ──
    # Strategy:
    #   - HTML forms: build body from extracted field names
    #   - API mode: try field name permutations with form-encoded, then JSON

    for attempt in range(MAX_RETRIES):
        result_data["attempts"] = attempt + 1

        # Build credential payload
        payload = _build_login_payload(login_email, login_password, fields, login_mode, attempt)
        if payload is None:
            # All permutations exhausted — fall through to retry/error logic
            last_error = last_error or ERROR_CODES.get("UNKNOWN_FAILURE", "Failed to build payload")
            break

        is_json_payload = payload.get("_is_json", False)
        # Only strip the internal _is_json flag — preserve all other fields
        # including CSRF tokens that may start with _ (e.g. _token, _csrf)
        body_data = {k: v for k, v in payload.items() if k != "_is_json"}

        try:
            method = fields.get("form_method", "POST")
            action_url = fields.get("form_action", login_url)
            if action_url and not action_url.startswith("http"):
                action_url = target.rstrip("/") + "/" + action_url.lstrip("/")

            if method == "GET":
                resp = http_session.get(
                    action_url, params=body_data, timeout=30, allow_redirects=True,
                )
            elif is_json_payload:
                resp = http_session.post(
                    action_url, json=body_data, timeout=30, allow_redirects=True,
                )
            else:
                resp = http_session.post(
                    action_url, data=body_data, timeout=30, allow_redirects=True,
                )

            # ── Handle response ──

            if resp.ok or resp.status_code in (302, 301, 200):
                body_text = resp.text.lower() if resp.text else ""

                # Check for login failure indicators in response
                if "invalid" in body_text or "incorrect" in body_text:
                    if attempt < MAX_RETRIES - 1:
                        last_error = ERROR_CODES["INVALID_CREDENTIALS"]
                        _rate_limit_backoff(attempt)
                        continue
                    return _fail_result("INVALID_CREDENTIALS", last_error, ctx)

                # Check for 2FA requirement
                if _detect_2fa(body_text):
                    return _fail_result("2FA_REQUIRED", ERROR_CODES["2FA_REQUIRED"], ctx)

                # Check for account locked
                if any(kw in body_text for kw in ("locked", "disabled", "suspended")):
                    return _fail_result("ACCOUNT_LOCKED", ERROR_CODES["ACCOUNT_LOCKED"], ctx)

                # ✅ Login succeeded
                ctx.session = http_session
                ctx.login_url = login_url
                ctx.email = login_email
                ctx.password = login_password
                ctx.cookie_string = _extract_cookie_string(http_session)
                ctx.authorization = _extract_jwt(http_session)

                result_data["status"] = "logged_in"
                result_data["content_type"] = resp.headers.get("Content-Type", "")

                return (
                    UnifiedToolResult(
                        tool_name="login",
                        status=ToolStatus.SUCCESS,
                        stdout=json.dumps(result_data),
                    ),
                    ctx,
                )

            # Non-success status code
            body_text = resp.text.lower() if resp.text else ""

            # 405/415 => wrong content type — switch to JSON if using form, or vice versa
            if resp.status_code in (405, 415) and not is_json_payload:
                logger.debug("Login: got %d with form-data, retrying with JSON", resp.status_code)
                last_error = f"HTTP {resp.status_code} with form-encoded data"
                continue  # next attempt toggles content type

            # 401/403 with invalid/incorrect in body = wrong credentials
            if resp.status_code in (401, 403):
                if "invalid" in body_text or "incorrect" in body_text:
                    if attempt < MAX_RETRIES - 1:
                        last_error = ERROR_CODES["INVALID_CREDENTIALS"]
                        _rate_limit_backoff(attempt)
                        continue
                    return _fail_result("INVALID_CREDENTIALS", last_error, ctx)

            if "rate" in body_text and "limit" in body_text:
                last_error = ERROR_CODES["RATE_LIMITED"]
                result_data["error_code"] = "RATE_LIMITED"
                _rate_limit_backoff(attempt)
                continue

            if any(kw in body_text for kw in ("locked", "disabled")):
                return _fail_result("ACCOUNT_LOCKED", ERROR_CODES["ACCOUNT_LOCKED"], ctx)

            last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            result_data["error_code"] = "UNKNOWN_FAILURE"

        except requests.RequestException as exc:
            last_error = str(exc)
            result_data["error_code"] = "NETWORK_ERROR"
            _rate_limit_backoff(attempt)
            continue

    # All retries exhausted
    result_data["error"] = last_error
    return (
        UnifiedToolResult(
            tool_name="login",
            status=ToolStatus.NONZERO_EXIT,
            stdout=json.dumps(result_data),
            stderr=last_error or ERROR_CODES["UNKNOWN_FAILURE"],
        ),
        ctx,
    )


def _build_login_payload(
    email: str,
    password: str,
    fields: dict[str, str],
    mode: str,
    attempt: int,
) -> dict[str, str | bool] | None:
    """Build the credential payload for a login attempt.

    For HTML form mode: uses the extracted field names, toggling JSON
    on odd attempts so 405/415 responses can recover.
    For API mode: builds all (permutation, content_type) combinations
    into a flat list so each combination gets a fair try.

    Returns:
        Dict with credential fields plus a ``_is_json`` boolean, or None
        if all combinations exhausted.
    """
    if mode == "form" and fields.get("email") and fields.get("password"):
        # HTML form with known field names — always use form-encoded.
        # JSON body would break CSRF validation (servers read CSRF from
        # form data, not JSON) and field name extraction.
        payload: dict[str, str | bool] = {
            fields["email"]: email,
            fields["password"]: password,
            "_is_json": False,
        }
        if fields.get("csrf_value"):
            csrf_field = fields.get("csrf", "csrf_token")
            payload[csrf_field] = fields["csrf_value"]
        return payload

    # API mode — build all (permutation, content_type) combinations flat
    all_combos: list[tuple[tuple[str, str], bool]] = []
    for perm in _API_FIELD_PERMUTATIONS:
        all_combos.append((perm, False))  # form-encoded first
        all_combos.append((perm, True))   # then JSON

    if attempt >= len(all_combos):
        return None  # all combinations exhausted

    (id_key, pw_key), use_json = all_combos[attempt]
    payload: dict[str, str | bool] = {
        id_key: email,
        pw_key: password,
        "_is_json": use_json,
    }

    logger.debug(
        "API login attempt %d: fields=(%s, %s), json=%s",
        attempt, id_key, pw_key, use_json,
    )
    return payload


# ── Internal helpers ──


def _detect_2fa(body: str) -> bool:
    """Detect if the login response indicates 2FA is required."""
    body_lower = body.lower()
    keywords = ["two-factor", "2fa", "otp", "authenticator",
                "verification code", "mfa", "multi-factor"]
    return any(kw in body_lower for kw in keywords)


def _extract_cookie_string(session: requests.Session) -> str | None:
    """Extract ``"name=value; name2=value2"`` cookie string from a session."""
    cookies = list(session.cookies)
    if not cookies:
        return None
    return "; ".join(f"{c.name}={c.value}" for c in cookies)


def _extract_jwt(session: requests.Session) -> str | None:
    """Extract JWT/bearer token from session cookies if present.

    Checks for common token cookie names and returns ``"Bearer <value>"``.
    """
    for cookie in session.cookies:
        if cookie.name.lower() in TOKEN_COOKIE_NAMES:
            return f"Bearer {cookie.value}"
    return None


def _rate_limit_backoff(attempt: int) -> None:
    """Sleep with jittered backoff based on attempt number."""
    if attempt >= len(BACKOFF_DELAYS):
        delay = float(BACKOFF_DELAYS[-1])
    else:
        delay = float(BACKOFF_DELAYS[attempt])
    jitter = random.uniform(0.5, 1.5)
    sleep_time = delay * jitter
    logger.debug("Rate limit backoff: sleeping %.1fs (attempt %d)", sleep_time, attempt)
    time.sleep(sleep_time)


def _fail_result(
    error_code: str,
    error_message: str,
    ctx: AuthContext,
) -> tuple[UnifiedToolResult, AuthContext | None]:
    """Build a failure UnifiedToolResult for login."""
    return (
        UnifiedToolResult(
            tool_name="login",
            status=ToolStatus.NONZERO_EXIT,
            stdout=json.dumps({
                "status": "failed",
                "error_code": error_code,
                "message": error_message,
            }),
            stderr=error_message,
        ),
        ctx,
    )
