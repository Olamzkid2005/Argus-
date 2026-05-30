"""
Form discovery utility — autonomous registration and login form detection.

Hybrid approach:
1. Check recon crawl data for auth-related paths
2. Fall back to scanning common registration/login endpoints
3. Parse HTML to extract form field names (email, password, CSRF, etc.)
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── Common auth endpoint paths (ordered by likelihood) ──

REGISTER_PATHS = [
    "/register",
    "/signup",
    "/sign-up",
    "/create-account",
    "/auth/register",
    "/api/register",
    "/api/auth/register",
    "/account/create",
    "/users/new",
]

LOGIN_PATHS = [
    "/login",
    "/signin",
    "/sign-in",
    "/auth/login",
    "/api/login",
    "/api/auth/login",
    "/account/login",
    "/auth",
    "/user/login",
]

# ── Error codes returned in ToolResult.stderr ──

ERROR_CODES: dict[str, str] = {
    # Registration errors
    "FORM_NOT_FOUND": "No registration/login form discovered on any common endpoint",
    "VALIDATION_FAILED": "Form submitted but server-side validation errors returned",
    "CAPTCHA_DETECTED": "CAPTCHA or bot detection blocked operation",
    "EMAIL_VERIFICATION_REQUIRED": (
        "Registration succeeded but email verification required "
        "and login after registration failed"
    ),
    "EMAIL_EXISTS": "Email already registered — account may exist from prior scan",
    "RATE_LIMITED": "Rate limited during attempt",
    "PASSWORD_REQUIREMENTS": "Password does not meet site requirements",
    # Login errors
    "INVALID_CREDENTIALS": "Login rejected — wrong email/password",
    "ACCOUNT_LOCKED": "Account locked or disabled",
    "2FA_REQUIRED": "Two-factor authentication required",
    "SESSION_FAILED": "Login succeeded but no session cookie was set",
    # Generic
    "UNKNOWN_FAILURE": "Operation failed for unspecified reason",
    "UNEXPECTED_RESPONSE": "Response format unexpected",
}


def discover_auth_endpoints(
    target: str,
    session: requests.Session,
    recon_crawled_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Discover registration and login endpoints on the target.

    Hybrid approach:
    1. Check recon crawl data for auth-related paths.
    2. Fall back to scanning common auth endpoints.

    Args:
        target: Base URL of the target application.
        session: Requests session for HTTP calls.
        recon_crawled_paths: Optional list of paths discovered during recon phase.

    Returns:
        Dict with keys:
            register_url (str | None): Discovered registration page URL.
            login_url (str | None): Discovered login page URL.
            register_fields (dict): Mapping of logical field names to HTML ``name`` attrs.
            login_fields (dict): Mapping of logical field names to HTML ``name`` attrs.
    """
    result: dict[str, Any] = {
        "register_url": None,
        "login_url": None,
        "register_fields": {},
        "login_fields": {},
    }

    # Phase 1: Check recon crawl data
    if recon_crawled_paths:
        _check_recon_paths(recon_crawled_paths, target, result)

    # Phase 2: Scan common paths (fallback)
    if not result["register_url"]:
        _scan_common_paths(target, session, REGISTER_PATHS, result, "register")

    if not result["login_url"]:
        _scan_common_paths(target, session, LOGIN_PATHS, result, "login")

    # Extract form fields from discovered pages
    if result["register_url"]:
        try:
            resp = session.get(result["register_url"], timeout=15)
            if resp.ok:
                result["register_fields"] = _extract_form_fields(resp.text, "register")
        except requests.RequestException as exc:
            logger.debug("Failed to fetch register page for field extraction: %s", exc)

    if result["login_url"]:
        try:
            resp = session.get(result["login_url"], timeout=15)
            if resp.ok:
                result["login_fields"] = _extract_form_fields(resp.text, "login")
        except requests.RequestException as exc:
            logger.debug("Failed to fetch login page for field extraction: %s", exc)

    return result


# ── Internal helpers ──


def _check_recon_paths(
    recon_crawled_paths: list[str],
    target: str,
    result: dict[str, Any],
) -> None:
    """Scan recon crawl data for auth-related paths."""
    register_keywords = ["register", "signup", "create-account", "sign-up"]
    login_keywords = ["login", "signin", "sign-in"]

    for path in recon_crawled_paths:
        full_url = path if path.startswith("http") else f"{target.rstrip('/')}/{path.lstrip('/')}"
        path_lower = path.lower()

        if not result["register_url"] and any(kw in path_lower for kw in register_keywords):
            result["register_url"] = full_url
            logger.debug("Form discovery: found register URL from recon data: %s", full_url)

        if not result["login_url"] and any(kw in path_lower for kw in login_keywords):
            result["login_url"] = full_url
            logger.debug("Form discovery: found login URL from recon data: %s", full_url)


def _scan_common_paths(
    target: str,
    session: requests.Session,
    paths: list[str],
    result: dict[str, Any],
    form_type: str,
) -> None:
    """Probe common auth endpoints to find registration/login forms."""
    key = f"{form_type}_url"

    for path in paths:
        url = f"{target.rstrip('/')}/{path.lstrip('/')}"
        try:
            resp = session.get(url, timeout=15)
            if resp.ok and ("<input" in resp.text or "<form" in resp.text):
                result[key] = url
                logger.debug("Form discovery: found %s URL at %s", form_type, url)
                return
        except requests.RequestException:
            continue


def _extract_form_fields(html: str, form_type: str = "register") -> dict[str, str]:
    """Extract form field names from HTML.

    Parses the HTML to find the most likely auth form and maps logical
    field names (email, password, confirm, csrf) to their actual HTML
    ``name`` attribute values.

    Args:
        html: Raw HTML of the page.
        form_type: ``"register"`` or ``"login"`` (used for heuristics).

    Returns:
        Dict mapping logical field names to HTML ``name`` values.
    """
    fields: dict[str, str] = {}

    try:
        soup = BeautifulSoup(html, "lxml")

        # Find the most likely form — prefer one with a password field
        form = None
        for f in soup.find_all("form"):
            if f.find("input", {"type": "password"}):
                form = f
                break
        if not form:
            form = soup.find("form")
        if not form:
            logger.debug("Form discovery: no <form> tag found in HTML")
            return fields

        # Extract form action and method
        action = form.get("action", "")
        if action:
            fields["form_action"] = action
        fields["form_method"] = form.get("method", "post").upper()

        # Extract input fields
        for inp in form.find_all("input"):
            name = inp.get("name", "") or inp.get("id", "")
            if not name:
                continue
            input_type = inp.get("type", "text").lower()

            if input_type == "email" or "email" in name.lower():
                fields["email"] = name
            elif input_type == "password":
                name_lower = name.lower()
                if any(kw in name_lower for kw in ("confirm", "repeat", "verify")):
                    fields["confirm"] = name
                else:
                    fields["password"] = name
            elif "username" in name.lower() or "login" in name.lower():
                # May be the email field if no explicit email field found
                if "email" not in fields:
                    fields["email"] = name
            elif "csrf" in name.lower() or "token" in name.lower() or "_token" == name:
                fields["csrf"] = name
                csrf_value = inp.get("value", "")
                if csrf_value:
                    fields["csrf_value"] = csrf_value

    except Exception as exc:
        logger.debug("Form discovery: error parsing HTML: %s", exc)

    return fields


def has_verification_requirement(resp: requests.Response) -> bool:
    """Check if the response suggests email verification is required.

    Looks for keywords in the response body or redirect chain that
    indicate the site requires email verification before login.

    Args:
        resp: The HTTP response to check.

    Returns:
        True if verification keywords are detected.
    """
    if not resp.text:
        return False

    body = resp.text.lower()
    verification_keywords = [
        "verify your email",
        "confirm your email",
        "activation link",
        "account activation",
        "please verify",
        "verification email",
        "confirm your account",
    ]
    return any(kw in body for kw in verification_keywords)
