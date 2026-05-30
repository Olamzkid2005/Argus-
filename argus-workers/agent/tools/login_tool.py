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
from tools.models import ToolResult

logger = logging.getLogger(__name__)

# ── Constants ──

MAX_RETRIES = 3
BACKOFF_DELAYS = [5, 30, 60]

# Cookie names that indicate a JWT/bearer token
TOKEN_COOKIE_NAMES = frozenset({
    "token", "jwt", "access_token", "authorization",
    "id_token", "refresh_token", "bearer",
})


# ── Public API ──


def run_login(
    target: str,
    http_session: requests.Session,
    auth_context: AuthContext | None = None,
    email: str | None = None,
    password: str | None = None,
    recon_crawled_paths: list[str] | None = None,
) -> tuple[ToolResult, AuthContext | None]:
    """Execute the login tool.

    Discovers login form → submits credentials → captures session →
    returns AuthContext.

    Args:
        target: Base URL of the target application.
        http_session: Requests session for HTTP calls.
        auth_context: Optional existing auth context (provides stored credentials).
        email: Optional email override. Falls back to auth_context.email.
        password: Optional password override. Falls back to auth_context.password.
        recon_crawled_paths: Optional list of discovered paths from recon phase.

    Returns:
        Tuple of (ToolResult, updated AuthContext or None).
    """
    ctx = auth_context or AuthContext()

    # Use provided credentials or fall back to stored credentials
    login_email = email or ctx.email
    login_password = password or ctx.password

    if not login_email or not login_password:
        return (
            ToolResult(
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
                success=False,
                tool="login",
            ),
            ctx,
        )

    # Discover login endpoint
    endpoints = discover_auth_endpoints(target, http_session, recon_crawled_paths)
    login_url = endpoints.get("login_url")

    if not login_url:
        return (
            ToolResult(
                stdout=json.dumps({
                    "status": "failed",
                    "error_code": "FORM_NOT_FOUND",
                    "message": ERROR_CODES["FORM_NOT_FOUND"],
                }),
                stderr=ERROR_CODES["FORM_NOT_FOUND"],
                success=False,
                tool="login",
            ),
            ctx,
        )

    fields = endpoints.get("login_fields", {})
    last_error: str | None = None
    result_data: dict[str, Any] = {
        "status": "failed",
        "login_url": login_url,
        "attempts": 0,
    }

    # Attempt login with retries
    for attempt in range(MAX_RETRIES):
        result_data["attempts"] = attempt + 1

        form_data: dict[str, str] = {}
        if fields.get("email"):
            form_data[fields["email"]] = login_email
        if fields.get("password"):
            form_data[fields["password"]] = login_password

        try:
            method = fields.get("form_method", "POST")
            action_url = fields.get("form_action", login_url)
            if action_url and not action_url.startswith("http"):
                action_url = target.rstrip("/") + "/" + action_url.lstrip("/")

            if method == "GET":
                resp = http_session.get(
                    action_url, params=form_data, timeout=30, allow_redirects=True,
                )
            else:
                resp = http_session.post(
                    action_url, data=form_data, timeout=30, allow_redirects=True,
                )

            if resp.ok or resp.status_code in (302, 301, 200):
                body = resp.text.lower() if resp.text else ""

                # Check for login failure indicators in response
                if "invalid" in body or "incorrect" in body:
                    if attempt < MAX_RETRIES - 1:
                        last_error = ERROR_CODES["INVALID_CREDENTIALS"]
                        _rate_limit_backoff(attempt)
                        continue
                    return _fail_result("INVALID_CREDENTIALS", last_error, ctx)

                # Check for 2FA requirement
                if _detect_2fa(body):
                    return _fail_result("2FA_REQUIRED", ERROR_CODES["2FA_REQUIRED"], ctx)

                # Check for account locked
                if "locked" in body or "disabled" in body or "suspended" in body:
                    return _fail_result("ACCOUNT_LOCKED", ERROR_CODES["ACCOUNT_LOCKED"], ctx)

                # ✅ Login succeeded
                ctx.session = http_session
                ctx.login_url = login_url
                ctx.email = login_email
                ctx.password = login_password
                ctx.cookie_string = _extract_cookie_string(http_session)
                ctx.authorization = _extract_jwt(http_session)

                result_data["status"] = "logged_in"

                return (
                    ToolResult(
                        stdout=json.dumps(result_data),
                        success=True,
                        tool="login",
                    ),
                    ctx,
                )

            # Non-success status code
            body = resp.text.lower() if resp.text else ""
            if "rate" in body and "limit" in body:
                last_error = ERROR_CODES["RATE_LIMITED"]
                result_data["error_code"] = "RATE_LIMITED"
                _rate_limit_backoff(attempt)
                continue
            if "locked" in body or "disabled" in body:
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
        ToolResult(
            stdout=json.dumps(result_data),
            stderr=last_error or ERROR_CODES["UNKNOWN_FAILURE"],
            success=False,
            tool="login",
        ),
        ctx,
    )


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
) -> tuple[ToolResult, AuthContext | None]:
    """Build a failure ToolResult for login."""
    return (
        ToolResult(
            stdout=json.dumps({
                "status": "failed",
                "error_code": error_code,
                "message": error_message,
            }),
            stderr=error_message,
            success=False,
            tool="login",
        ),
        ctx,
    )
