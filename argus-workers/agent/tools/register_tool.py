"""
register tool — autonomous account creation for the LLM agent.

Discovers registration forms, generates credentials, submits registration,
and returns an AuthContext with the authenticated session on success.
"""

from __future__ import annotations

import json
import secrets
import string
import uuid
from typing import Any

import requests

from agent.auth_context import AuthContext
from tools.models import ToolResult

# ── Constants ──

MAX_RETRIES = 3

# Backoff delays (seconds) per attempt, with ±50% jitter applied at runtime.
BACKOFF_DELAYS = [5, 30, 60]


def generate_credentials() -> tuple[str, str]:
    """Generate random test credentials.

    Returns:
        Tuple of (email, password).
    """
    rand = uuid.uuid4().hex[:8]
    email = f"argus_pentest_{rand}@temp-mail.org"
    password = _generate_password()
    return email, password


def _generate_password(length: int = 16) -> str:
    """Generate a strong random password meeting common requirements.

    Guarantees at least one uppercase, one lowercase, one digit, and
    one special character.
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


def run_register(
    target: str,
    http_session: requests.Session,
    auth_context: AuthContext | None = None,
    recon_crawled_paths: list[str] | None = None,
) -> tuple[ToolResult, AuthContext | None]:
    """Execute the register tool.

    This is a skeleton implementation for Phase 2b.
    Full form discovery and submission logic will be added in Phase 5.

    Args:
        target: Base URL of the target application.
        http_session: Requests session for HTTP calls.
        auth_context: Optional existing auth context.
        recon_crawled_paths: Optional list of discovered paths from recon phase.

    Returns:
        Tuple of (ToolResult, updated AuthContext or None).
    """
    # TODO: Implement full form discovery and registration logic.
    # For now, return a placeholder indicating the tool exists.
    ctx = auth_context or AuthContext()
    return (
        ToolResult(
            stdout=json.dumps({
                "status": "not_implemented",
                "message": "register tool skeleton — full implementation pending (Phase 5)",
            }),
            success=False,
            tool="register",
        ),
        ctx,
    )
