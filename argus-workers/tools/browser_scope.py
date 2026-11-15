"""Authorization for the browser scan subprocess.

The browser scan runs Playwright in a separate process so a crash or hang cannot
take the orchestrator with it. A subprocess cannot see the in-process run scope,
so the parent passes the authorization explicitly (``ARGUS_BROWSER_SCOPE``) and
the worker applies the same decision to the top-level URL, to every navigation
it performs, and to every request the page makes on its own.

Everything here goes through ``tools.scope_validator.authorize_target``: parsed
components, typed scope entries, one decision. With no explicit scope the
worker falls back to the top-level target's own origin, exactly like the
in-process browser engine, so an open redirect or an injected subresource cannot
reach another host.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from tools.scope_validator import TargetParseError, authorize_target, parse_target

logger = logging.getLogger(__name__)

#: Environment variable carrying the run's authorization into the subprocess.
SCOPE_ENV_VAR = "ARGUS_BROWSER_SCOPE"


@dataclass(frozen=True)
class BrowserScopePayload:
    """The run authorization handed to the browser worker."""

    mode: str = "allowlist"
    allowed_targets: tuple[str, ...] = ()
    blocked_targets: tuple[str, ...] = ()

    @property
    def configured(self) -> bool:
        """True when the payload states a policy rather than "nothing passed"."""
        return self.mode == "open" or bool(self.allowed_targets or self.blocked_targets)

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "allowed_targets": list(self.allowed_targets),
            "blocked_targets": list(self.blocked_targets),
        }


def parse_scope_payload(raw: str | dict | None) -> BrowserScopePayload | None:
    """Parse the JSON/dict authorization passed by the parent, or None.

    Malformed input yields None rather than a permissive default: the worker
    then falls back to same-origin pinning, which can only narrow what it
    reaches.
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Ignoring malformed browser scope payload")
            return None
    if not isinstance(raw, dict):
        return None

    mode = str(raw.get("mode") or "allowlist").strip().lower()
    if mode not in ("allowlist", "warn", "open"):
        mode = "allowlist"

    def _entries(key: str) -> tuple[str, ...]:
        value = raw.get(key) or []
        if isinstance(value, str):
            value = [value]
        try:
            return tuple(str(entry) for entry in value if str(entry).strip())
        except TypeError:
            return ()

    payload = BrowserScopePayload(
        mode=mode,
        allowed_targets=_entries("allowed_targets"),
        blocked_targets=_entries("blocked_targets"),
    )
    return payload if payload.configured else None


def request_authorized(
    url: str,
    target_url: str,
    scope: BrowserScopePayload | None = None,
) -> bool:
    """Whether this request may be made from the browser scan.

    With an explicit scope the run's authorization decides; without one the
    scan target's own origin is the only origin reachable.
    """
    if scope is not None and scope.configured:
        decision = authorize_target(
            url,
            None,
            mode=scope.mode,
            allowed_targets=list(scope.allowed_targets),
            blocked_targets=list(scope.blocked_targets),
        )
        return decision.authorized
    # No explicit scope: authorize a host-form or malformed value on its own
    # terms first, then require the scan target's origin.
    try:
        parse_target(url)
    except TargetParseError:
        return False
    return authorize_target(url, None, allow_origin=target_url).authorized


def navigation_authorized(
    url: str,
    target_url: str,
    scope: BrowserScopePayload | None = None,
) -> bool:
    """Whether the worker may navigate to this URL itself."""
    return request_authorized(url, target_url, scope)
