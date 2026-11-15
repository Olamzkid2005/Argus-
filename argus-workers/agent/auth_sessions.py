"""Identity-scoped authentication sessions (Stage 5.2).

The agent kept one ``AuthContext`` on the instance, so every tool after a login
used the last identity — in a two-user assessment the second login silently
replaced the first, and a verifier could read user B's session while claiming to
test user A. This module keeps sessions per ``(engagement, identity)``, hands
out only the requested identity's headers, verifies a session against a
protected resource before treating it as valid, performs at most one refresh
when it expired, and raises a distinguishable ``AuthExpiredError`` so a caller
pauses instead of continuing anonymously.

It also owns the redaction helpers that keep credentials and tokens out of
prompts, decision arguments, reports and caches.
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from agent.auth_context import AuthContext


def _now() -> str:
    return datetime.now(UTC).isoformat()


class AuthSessionError(RuntimeError):
    """An authentication session problem with a machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class AuthExpiredError(AuthSessionError):
    """The identity's session expired and could not be refreshed safely."""

    def __init__(self, engagement_id: str, identity: str, message: str) -> None:
        super().__init__(
            "auth-expired",
            f"authentication for {identity or 'unknown identity'} in engagement "
            f"{engagement_id} is no longer valid: {message}. The run must pause "
            "for operator credentials instead of continuing unauthenticated.",
        )
        self.engagement_id = engagement_id
        self.identity = identity


@dataclass
class IdentitySession:
    """One identity's authentication state inside one engagement."""

    engagement_id: str
    identity: str
    context: AuthContext
    established_at: str = field(default_factory=_now)
    last_verified_at: str = ""
    refresh_count: int = 0
    expired: bool = False

    def headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.context.cookie_string:
            headers["Cookie"] = self.context.cookie_string
        if self.context.authorization:
            headers["Authorization"] = self.context.authorization
        if self.context.csrf_token:
            headers["X-CSRF-Token"] = self.context.csrf_token
        return headers

    def snapshot(self) -> dict[str, Any]:
        """Safe view: identity and timing only, never tokens or credentials."""
        return {
            "engagement_id": self.engagement_id,
            "identity": self.identity,
            "established_at": self.established_at,
            "last_verified_at": self.last_verified_at,
            "refresh_count": self.refresh_count,
            "expired": self.expired,
        }


#: Keys whose values are secrets in any surface the agent emits.
SECRET_KEY_MARKERS = (
    "password",
    "passwd",
    "pwd",
    "token",
    "authorization",
    "cookie",
    "secret",
    "api_key",
    "apikey",
    "csrf",
    "credential",
    "session",
)

REDACTED = "***REDACTED***"


def is_secret_key(key: str) -> bool:
    lowered = str(key).lower().replace("-", "_")
    return any(marker in lowered for marker in SECRET_KEY_MARKERS)


def redact_arguments(arguments: Any) -> Any:
    """Recursively replace secret-looking values with a fixed marker."""
    if isinstance(arguments, dict):
        return {
            key: REDACTED if is_secret_key(key) else redact_arguments(value)
            for key, value in arguments.items()
        }
    if isinstance(arguments, list):
        return [redact_arguments(item) for item in arguments]
    if isinstance(arguments, tuple):
        return tuple(redact_arguments(item) for item in arguments)
    return arguments


def redact_text(text: str, secrets: list[str] | tuple[str, ...] | None = None) -> str:
    """Remove known secret values from arbitrary text."""
    redacted = text
    for secret in secrets or ():
        if secret:
            redacted = redacted.replace(str(secret), REDACTED)
    return redacted


def collects_secrets(text: str, secrets: list[str] | tuple[str, ...] | None = None) -> bool:
    """Whether any known secret value appears in text."""
    return any(secret and str(secret) in text for secret in (secrets or ()))


class EngagementAuthSessions:
    """Sessions per engagement and identity, isolated from each other."""

    def __init__(self) -> None:
        self._sessions: dict[tuple[str, str], IdentitySession] = {}
        self._lock = threading.Lock()

    def store(
        self,
        engagement_id: str,
        identity: str,
        context: AuthContext,
    ) -> IdentitySession:
        if not engagement_id:
            raise AuthSessionError("engagement-required", "an auth session must belong to an engagement")
        if not identity:
            raise AuthSessionError("identity-required", "an auth session must be scoped to an identity")
        session = IdentitySession(
            engagement_id=engagement_id,
            identity=identity,
            context=context,
        )
        with self._lock:
            self._sessions[(engagement_id, identity)] = session
        return session

    def get(self, engagement_id: str, identity: str) -> IdentitySession | None:
        with self._lock:
            session = self._sessions.get((engagement_id, identity))
            return copy.deepcopy(session) if session is not None else None

    def context_for(self, engagement_id: str, identity: str) -> AuthContext | None:
        """The stored context of exactly this identity, or None."""
        session = self.get(engagement_id, identity)
        return session.context if session is not None else None

    def identities(self, engagement_id: str) -> list[str]:
        with self._lock:
            return sorted(
                identity
                for (eng, identity) in self._sessions
                if eng == engagement_id
            )

    def headers_for(self, engagement_id: str, identity: str) -> dict[str, str]:
        """Headers for exactly this identity; never another identity's session."""
        session = self.get(engagement_id, identity)
        if session is None:
            raise AuthSessionError(
                "unknown-identity",
                f"no authentication session for {identity or 'unknown identity'} in engagement {engagement_id}",
            )
        if session.expired:
            raise AuthExpiredError(engagement_id, identity, "session is marked expired")
        return session.headers()

    def verify(
        self,
        engagement_id: str,
        identity: str,
        check: Callable[[AuthContext], bool],
        refresh: Callable[[IdentitySession], AuthContext] | None = None,
    ) -> IdentitySession:
        """Verify the session against a protected identity check.

        A valid session is timestamped. An invalid one is marked expired and
        refreshed **once**; if the refresh does not produce a session that
        passes the same check, ``AuthExpiredError`` is raised so the caller can
        pause for operator input rather than treat anonymous access as success.
        """
        session = self.get(engagement_id, identity)
        if session is None:
            raise AuthSessionError(
                "unknown-identity",
                f"no authentication session for {identity or 'unknown identity'} in engagement {engagement_id}",
            )

        if check(session.context):
            session.expired = False
            session.last_verified_at = _now()
            self._replace(session)
            return session

        session.expired = True
        self._replace(session)

        if refresh is None:
            raise AuthExpiredError(engagement_id, identity, "protected check failed and no refresh is configured")
        if session.refresh_count >= 1:
            raise AuthExpiredError(
                engagement_id,
                identity,
                "protected check failed after the single allowed refresh",
            )

        refreshed_context = refresh(session)
        session.context = refreshed_context
        session.refresh_count += 1
        if not check(refreshed_context):
            session.expired = True
            self._replace(session)
            raise AuthExpiredError(
                engagement_id,
                identity,
                "refreshed session still fails the protected identity check "
                "(the single allowed refresh is exhausted)",
            )

        session.expired = False
        session.last_verified_at = _now()
        self._replace(session)
        return session

    def invalidate(self, engagement_id: str, identity: str) -> None:
        session = self.get(engagement_id, identity)
        if session is not None:
            session.expired = True
            self._replace(session)

    def snapshot(self, engagement_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [
                copy.deepcopy(session).snapshot()
                for (eng, _identity), session in sorted(self._sessions.items())
                if eng == engagement_id
            ]

    def _replace(self, session: IdentitySession) -> None:
        with self._lock:
            self._sessions[(session.engagement_id, session.identity)] = session
