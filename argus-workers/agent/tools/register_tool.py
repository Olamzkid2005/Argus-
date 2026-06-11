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
import signal
import string
import threading
import time
import uuid
from typing import Any

import requests

from agent.auth_context import AuthContext
from agent.form_discovery import (
    ERROR_CODES,
    discover_auth_endpoints,
    has_verification_requirement,
)
from tool_core.result import ToolStatus, UnifiedToolResult

logger = logging.getLogger(__name__)

# ── Constants ──

MAX_RETRIES = 6

# Backoff delays (seconds) per attempt (0-indexed), with ±50% jitter.
BACKOFF_DELAYS = [1, 2, 3, 3, 5, 5]

# ── Common API field name permutations for API-style registration ──
# When no HTML form fields are available (API mode), the register tool
# iterates through these combinations to find the right field names.
_API_FIELD_PERMUTATIONS: list[tuple[str, str]] = [
    ("email", "password"),       # most common for modern APIs
    ("username", "password"),    # common for legacy systems
    ("email", "pass"),           # shorter variant
    ("username", "pass"),        # shorter variant
    ("user", "password"),        # user/password
]


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
    register_url: str | None = None,
) -> tuple[UnifiedToolResult, AuthContext | None]:
    """Execute the register tool.

    Discovers registration form → generates credentials → submits form →
    verifies login works → returns AuthContext with session.

    Supports both HTML-form-based registration (discovers form fields automatically)
    and API-style registration (JSON body with common field name permutations).

    Has a hard deadline of ~150s via SIGALRM so the tool never hangs
    indefinitely and always returns within the MCP/TypeScript timeout budget.

    Args:
        target: Base URL of the target application.
        http_session: Requests session for HTTP calls.
        auth_context: Optional existing auth context.
        recon_crawled_paths: Optional list of discovered paths from recon phase.
        register_url: Optional direct registration URL override (skips discovery if provided).

    Returns:
        Tuple of (UnifiedToolResult, updated AuthContext or None).
    """
    # Hard deadline: raise TimeoutError if not done within 150s
    _TIMEOUT_SECONDS = 150
    _timeout_occurred = False

    # ── Platform-aware deadline ──
    # Unix: use SIGALRM (alertable from any blocking syscall)
    # Windows / non-main-thread: use a threading.Timer that sets a flag;
    #   the inner loop checks the flag between requests.
    _use_alarm = hasattr(signal, "SIGALRM")
    _timeout_flag: list[bool] = [False]  # mutable container for thread closure

    if _use_alarm:
        def _timeout_handler(_signum, _frame):
            raise TimeoutError(f"Register tool timed out after {_TIMEOUT_SECONDS}s")
        try:
            signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(_TIMEOUT_SECONDS)
        except (ValueError, AttributeError):
            _use_alarm = False

    if not _use_alarm:
        # Threading fallback for Windows / non-main-thread
        def _thread_timeout():
            _timeout_flag[0] = True
        _timer = threading.Timer(_TIMEOUT_SECONDS, _thread_timeout)
        _timer.daemon = True
        _timer.start()

    try:
        # ── Start of inner logic ──
        ctx = auth_context or AuthContext()
        result_data: dict[str, Any] = {"status": "failed", "attempts": 0}
        last_error: str | None = None

        # Step 1: Discover registration endpoint (or use provided register_url override)
        if register_url:
            endpoints = {
                "register_url": register_url,
                "login_url": None,
                "register_fields": {},
                "login_fields": {},
            }
            logger.debug("Register: using provided register_url='%s'", register_url)
        else:
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
        login_mode = "api" if not fields.get("email") and not fields.get("password") else "form"
        result_data["register_url"] = register_url
        result_data["register_mode"] = login_mode

        # Step 2: Attempt registration (with retries)
        for attempt in range(MAX_RETRIES):
            # Check threading-based deadline flag (Windows fallback)
            if _timeout_flag[0]:
                raise TimeoutError(f"Register tool timed out after {_TIMEOUT_SECONDS}s")
            email, password = generate_credentials()
            result_data["attempts"] = attempt + 1

            # Build payload using the shared helper
            payload = _build_register_payload(
                email, password, fields, login_mode, attempt,
            )
            if payload is None:
                last_error = last_error or ERROR_CODES.get("UNKNOWN_FAILURE", "Failed to build payload")
                break

            is_json_payload = payload.get("_is_json", False)
            # Only strip the internal _is_json flag — preserve all other fields
            body_data = {k: v for k, v in payload.items() if k != "_is_json"}

            # Determine action URL and method
            method = fields.get("form_method", "POST")
            action_url = fields.get("form_action", register_url)
            if action_url and not action_url.startswith("http"):
                action_url = target.rstrip("/") + "/" + action_url.lstrip("/")

            try:
                if method == "GET":
                    resp = http_session.get(action_url, params=body_data, timeout=15)
                elif is_json_payload:
                    resp = http_session.post(action_url, json=body_data, timeout=15)
                else:
                    resp = http_session.post(action_url, data=body_data, timeout=15)

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
                        _rate_limit_backoff(attempt)
                        continue

                else:
                    # Check response body for specific errors
                    body = resp.text.lower() if resp.text else ""

                    # 405/415 => wrong content type
                    if resp.status_code in (405, 415) and not is_json_payload:
                        logger.debug("Register: got %d with form-data, retrying with JSON", resp.status_code)
                        last_error = f"HTTP {resp.status_code} with form-encoded data"
                        continue  # next attempt toggles content type

                    if "captcha" in body or "bot" in body or "recaptcha" in body or "robot" in body:
                        last_error = ERROR_CODES["CAPTCHA_DETECTED"]
                        result_data["error_code"] = "CAPTCHA_DETECTED"
                        break  # Don't retry CAPTCHA

                    if "already exist" in body or "already taken" in body or "already registered" in body:
                        last_error = ERROR_CODES["EMAIL_EXISTS"]
                        result_data["error_code"] = "EMAIL_EXISTS"
                        _rate_limit_backoff(attempt)
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

    except TimeoutError as e:
        # Hard deadline hit — return timeout result
        return (
            UnifiedToolResult(
                tool_name="register",
                status=ToolStatus.NONZERO_EXIT,
                stdout=json.dumps({"status": "timed_out", "error": str(e)}),
                stderr=str(e),
            ),
            auth_context or AuthContext(),
        )
    finally:
        try:
            signal.alarm(0)  # Cancel pending alarm (Unix)
        except (ValueError, AttributeError):
            pass
        if not _use_alarm:
            try:
                _timer.cancel()  # Cancel threading timer (Windows)
            except (NameError, AttributeError):
                pass


# ── Internal helpers ──


def _build_register_payload(
    email: str,
    password: str,
    fields: dict[str, str],
    mode: str,
    attempt: int,
) -> dict[str, str | bool] | None:
    """Build the credential payload for a registration attempt.

    For HTML form mode: uses the extracted field names, always form-encoded
    (JSON would break CSRF token delivery).
    For API mode: builds all (permutation, content_type) combinations
    into a flat list so each combination gets a fair try.

    Returns:
        Dict with credential fields plus a ``_is_json`` boolean, or None
        if all combinations exhausted.
    """
    if mode == "form" and fields.get("email") and fields.get("password"):
        # HTML form with known field names — always form-encoded
        payload: dict[str, str | bool] = {
            fields["email"]: email,
            fields["password"]: password,
            "_is_json": False,
        }
        if fields.get("confirm"):
            payload[fields["confirm"]] = password
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
    return payload


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

    Supports both HTML-form-based login (extracted fields with CSRF) and
    API-style login (field name permutations + JSON body).

    Returns:
        Dict with keys: success (bool), requires_verification (bool),
        error (str | None), login_url (str | None).
    """
    login_url = endpoints.get("login_url")
    if not login_url:
        return {"success": False, "error": "No login URL discovered"}

    fields = endpoints.get("login_fields", {})
    login_mode = endpoints.get("login_mode", "api" if not fields else "form")

    # Build a single combo for form mode (with CSRF if available)
    # or all (permutation, content_type) combinations for API mode
    from agent.tools.login_tool import _build_login_payload

    if login_mode == "form" and fields.get("email") and fields.get("password"):
        # Use the shared login payload builder for consistency
        payload = _build_login_payload(email, password, fields, "form", 0)
        if payload is None:
            return {"success": False, "error": "Failed to build login payload"}
        body_data = {k: v for k, v in payload.items() if k != "_is_json"}

        # Resolve action URL (form action may differ from the discovered login URL)
        action_url = fields.get("form_action", login_url)
        if action_url and not action_url.startswith("http"):
            action_url = target.rstrip("/") + "/" + action_url.lstrip("/")

        try:
            resp = session.post(action_url, data=body_data, timeout=15, allow_redirects=True)
        except requests.RequestException as exc:
            return {"success": False, "error": str(exc)}

        if resp.ok or resp.status_code in (302, 301):
            if has_verification_requirement(resp):
                return {"success": False, "requires_verification": True, "login_url": login_url}
            body = resp.text.lower() if resp.text else ""
            if "invalid" in body or "incorrect" in body:
                return {"success": False, "error": "Invalid credentials"}
            return {"success": True, "login_url": login_url}

        return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text[:100]}"}

    # API mode: try all (permutation, content_type) combinations
    from agent.tools.login_tool import _API_FIELD_PERMUTATIONS as _LOGIN_PERMUTATIONS

    for (id_key, pw_key), use_json in ((p, f) for p in _LOGIN_PERMUTATIONS for f in (False, True)):
        body_data = {id_key: email, pw_key: password}

        try:
            if use_json:
                resp = session.post(login_url, json=body_data, timeout=15, allow_redirects=True)
            else:
                resp = session.post(login_url, data=body_data, timeout=15, allow_redirects=True)

            if resp.ok or resp.status_code in (302, 301):
                if has_verification_requirement(resp):
                    return {"success": False, "requires_verification": True, "login_url": login_url}
                body = resp.text.lower() if resp.text else ""
                if "invalid" in body or "incorrect" in body:
                    continue
                return {"success": True, "login_url": login_url}

            body = resp.text.lower() if resp.text else ""
            if resp.status_code in (405, 415):
                continue
            if "invalid" in body or "incorrect" in body:
                continue
            if "rate" in body and "limit" in body:
                return {"success": False, "error": "Rate limited"}

        except requests.RequestException:
            continue

    return {"success": False, "error": "Login failed after registration"}


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
