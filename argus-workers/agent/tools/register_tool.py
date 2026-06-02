"""
register tool — autonomous account creation for the LLM agent.

Discovers registration forms, generates credentials, submits registration,
handles retries with jittered backoff, and returns an AuthContext with the
authenticated session on success.

Flow:
1. Discover registration endpoint (hybrid: recon data + common paths)
2. Extract form fields (email, password, CSRF token)
3. Generate random credentials
4. Submit registration form
5. Try logging in immediately with created credentials
6. Handle email verification fallback
7. Return AuthContext with session on success
"""

from __future__ import annotations

import json
import logging
import random
import secrets
import string
import time
import uuid
from typing import Any

import requests

from agent.auth_context import AuthContext
from agent.form_discovery import (
    ERROR_CODES,
    _extract_form_fields,
    discover_auth_endpoints,
    has_verification_requirement,
)
from tool_core.result import ToolStatus, UnifiedToolResult

logger = logging.getLogger(__name__)

# ── Constants ──

MAX_RETRIES = 3

# Backoff delays (seconds) per attempt (0-indexed), with ±50% jitter.
BACKOFF_DELAYS = [5, 30, 60]


# ── Public API ──


def generate_credentials() -> tuple[str, str]:
    """Generate random test credentials.

    Returns:
        Tuple of (email, password).
    """
    rand = uuid.uuid4().hex[:8]
    email = f"argus_pentest_{rand}@temp-mail.org"
    password = _generate_password()
    return email, password


def run_register(
    target: str,
    http_session: requests.Session,
    auth_context: AuthContext | None = None,
    recon_crawled_paths: list[str] | None = None,
) -> tuple[UnifiedToolResult, AuthContext | None]:
    """Execute the register tool.

    Discovers registration form → generates credentials → submits form →
    verifies login works → returns AuthContext with session.

    Args:
        target: Base URL of the target application.
        http_session: Requests session for HTTP calls.
        auth_context: Optional existing auth context.
        recon_crawled_paths: Optional list of discovered paths from recon phase.

    Returns:
        Tuple of (UnifiedToolResult, updated AuthContext or None).
    """
    ctx = auth_context or AuthContext()
    result_data: dict[str, Any] = {"status": "failed", "attempts": 0}
    last_error: str | None = None

    # Step 1: Discover registration endpoint
    endpoints = discover_auth_endpoints(target, http_session, recon_crawled_paths)
    register_url = endpoints.get("register_url")

    if not register_url:
        return (
            UnifiedToolResult(
                tool_name="register",
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

    fields = endpoints.get("register_fields", {})
    result_data["register_url"] = register_url

    # Step 2: Attempt registration (with retries)
    for attempt in range(MAX_RETRIES):
        email, password = generate_credentials()
        result_data["attempts"] = attempt + 1

        # Build form data from discovered fields
        form_data: dict[str, str] = {}
        if fields.get("email"):
            form_data[fields["email"]] = email
        if fields.get("password"):
            form_data[fields["password"]] = password
        if fields.get("confirm"):
            form_data[fields["confirm"]] = password

        # Fetch CSRF token if needed (token may be per-request)
        if fields.get("csrf"):
            try:
                csrf_resp = http_session.get(register_url, timeout=15)
                if csrf_resp.ok:
                    fresh_fields = _extract_form_fields(csrf_resp.text, "register")
                    csrf_value = fresh_fields.get("csrf_value")
                    if csrf_value:
                        form_data[fields["csrf"]] = csrf_value
            except requests.RequestException:
                pass  # Proceed without CSRF token

        # Determine action URL and method
        method = fields.get("form_method", "POST")
        action_url = fields.get("form_action", register_url)
        if action_url and not action_url.startswith("http"):
            action_url = target.rstrip("/") + "/" + action_url.lstrip("/")

        try:
            if method == "GET":
                resp = http_session.get(action_url, params=form_data, timeout=30)
            else:
                resp = http_session.post(action_url, data=form_data, timeout=30)

            # Check response
            if resp.ok or resp.status_code in (302, 301):
                # Step 3: Try logging in immediately
                login_result = _try_login(
                    target, http_session, email, password, endpoints,
                )

                if login_result["success"]:
                    # ✅ Fully authenticated
                    ctx.session = http_session
                    ctx.email = email
                    ctx.password = password
                    ctx.register_url = register_url
                    ctx.login_url = login_result.get("login_url")
                    ctx.cookie_string = _extract_cookie_string(http_session)

                    result_data["status"] = "registered_and_logged_in"
                    result_data["email"] = email

                    return (
                        UnifiedToolResult(
                            tool_name="register",
                            status=ToolStatus.SUCCESS,
                            stdout=json.dumps(result_data),
                        ),
                        ctx,
                    )

                elif login_result.get("requires_verification"):
                    # ⚠️ Email verification required — store credentials for
                    # later login attempt but report the finding
                    ctx.email = email
                    ctx.password = password
                    ctx.register_url = register_url

                    result_data["status"] = "needs_verification"
                    result_data["email"] = email

                    return (
                        UnifiedToolResult(
                            tool_name="register",
                            status=ToolStatus.NONZERO_EXIT,
                            stdout=json.dumps(result_data),
                            stderr=ERROR_CODES["EMAIL_VERIFICATION_REQUIRED"],
                        ),
                        ctx,
                    )
                else:
                    last_error = login_result.get("error", "Login failed after registration")
                    continue

            else:
                # Check response body for specific errors
                body = resp.text.lower() if resp.text else ""

                if "captcha" in body or "bot" in body or "recaptcha" in body or "robot" in body:
                    last_error = ERROR_CODES["CAPTCHA_DETECTED"]
                    result_data["error_code"] = "CAPTCHA_DETECTED"
                    break  # Don't retry CAPTCHA

                if "already exist" in body or "already taken" in body or "already registered" in body:
                    last_error = ERROR_CODES["EMAIL_EXISTS"]
                    result_data["error_code"] = "EMAIL_EXISTS"
                    _rate_limit_backoff(attempt)  # Brief pause before retry
                    continue

                if "rate" in body and "limit" in body:
                    last_error = ERROR_CODES["RATE_LIMITED"]
                    result_data["error_code"] = "RATE_LIMITED"
                    _rate_limit_backoff(attempt)
                    continue

                # Validation error — try again
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                result_data["error_code"] = "VALIDATION_FAILED"

        except requests.RequestException as exc:
            last_error = str(exc)
            result_data["error_code"] = "UNKNOWN_FAILURE"
            _rate_limit_backoff(attempt)
            continue

    # All retries exhausted
    result_data["error"] = last_error
    return (
        UnifiedToolResult(
            tool_name="register",
            status=ToolStatus.NONZERO_EXIT,
            stdout=json.dumps(result_data),
            stderr=last_error or ERROR_CODES["UNKNOWN_FAILURE"],
        ),
        ctx,
    )


# ── Internal helpers ──


def _generate_password(length: int = 16) -> str:
    """Generate a strong random password meeting common complexity requirements.

    Guarantees at least one lowercase, one uppercase, one digit, and one
    special character from ``!@#$%^&*``.
    """
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    password = [
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%^&*"),
    ]
    password += [secrets.choice(chars) for _ in range(length - 4)]
    secrets.SystemRandom().shuffle(password)
    return "".join(password)


def _try_login(
    target: str,
    session: requests.Session,
    email: str,
    password: str,
    endpoints: dict[str, Any],
) -> dict[str, Any]:
    """Attempt to log in with created credentials after registration.

    Returns:
        Dict with keys: success (bool), requires_verification (bool),
        error (str | None), login_url (str | None).
    """
    login_url = endpoints.get("login_url")
    if not login_url:
        return {"success": False, "error": "No login URL discovered"}

    fields = endpoints.get("login_fields", {})

    form_data: dict[str, str] = {}
    if fields.get("email"):
        form_data[fields["email"]] = email
    if fields.get("password"):
        form_data[fields["password"]] = password

    try:
        method = fields.get("form_method", "POST")
        action_url = fields.get("form_action", login_url)
        if action_url and not action_url.startswith("http"):
            action_url = target.rstrip("/") + "/" + action_url.lstrip("/")

        if method == "GET":
            resp = session.get(
                action_url, params=form_data, timeout=30, allow_redirects=True,
            )
        else:
            resp = session.post(
                action_url, data=form_data, timeout=30, allow_redirects=True,
            )

        if resp.ok or resp.status_code in (302, 301):
            # Check for verification requirement
            if has_verification_requirement(resp):
                return {
                    "success": False,
                    "requires_verification": True,
                    "login_url": login_url,
                }

            # Check for invalid credentials
            body = resp.text.lower() if resp.text else ""
            if "invalid" in body or "incorrect" in body:
                return {"success": False, "error": "Invalid credentials"}

            # Login likely succeeded
            return {"success": True, "login_url": login_url}

        # Non-OK response
        body = resp.text.lower() if resp.text else ""
        if "invalid" in body or "incorrect" in body:
            return {"success": False, "error": "Invalid credentials"}
        if "rate" in body and "limit" in body:
            return {"success": False, "error": "Rate limited"}

        return {"success": False, "error": f"HTTP {resp.status_code}"}

    except requests.RequestException as exc:
        return {"success": False, "error": str(exc)}


def _extract_cookie_string(session: requests.Session) -> str | None:
    """Extract cookie string from a requests Session."""
    cookies = list(session.cookies)
    if not cookies:
        return None
    return "; ".join(f"{c.name}={c.value}" for c in cookies)


def _rate_limit_backoff(attempt: int) -> None:
    """Sleep with jittered exponential backoff based on attempt number."""
    if attempt >= len(BACKOFF_DELAYS):
        delay = float(BACKOFF_DELAYS[-1])
    else:
        delay = float(BACKOFF_DELAYS[attempt])
    jitter = random.uniform(0.5, 1.5)
    sleep_time = delay * jitter
    logger.debug("Rate limit backoff: sleeping %.1fs (attempt %d)", sleep_time, attempt)
    time.sleep(sleep_time)
