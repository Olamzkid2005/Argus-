"""Memorist: redacted, tenant-scoped long-term knowledge (plan §4.8, P-16).

Writes pass through redaction first, so secrets and session material never enter
the memory store. Reads are scoped to the engagement's tenant and return only
rows marked redacted; an engagement with no tenant gets nothing back.
"""

from __future__ import annotations

import re
from typing import Any

from agent.delegation.models import DelegationError

_REDACTION_PATTERNS = (
    re.compile(
        r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|"
        r"authorization|session[_-]?id)\b\s*[:=]\s*\S+"
    ),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\b(?:set-)?cookie\s*:\s*\S+"),
    # Long opaque blobs: API keys, base64/hex tokens, private key material.
    re.compile(r"\b[A-Za-z0-9+/_-]{32,}={0,2}\b"),
)

REDACTED = "[REDACTED]"


def redact_secrets(text: str) -> tuple[str, int]:
    """Return ``(redacted_text, replacements)`` with secret material removed."""
    redacted = str(text or "")
    replacements = 0
    for pattern in _REDACTION_PATTERNS:
        redacted, count = pattern.subn(REDACTED, redacted)
        replacements += count
    return redacted, replacements


class Memorist:
    """Stores and retrieves reusable, redacted knowledge across tasks."""

    def __init__(self, store: Any, *, max_items: int = 5) -> None:
        self._store = store
        self.max_items = max_items

    def remember(
        self,
        engagement_id: str,
        text: str,
        *,
        kind: str = "fact",
    ) -> dict[str, Any]:
        if not text or not text.strip():
            raise DelegationError("nothing to remember")
        summary, replacements = redact_secrets(text)
        if not summary.strip():
            raise DelegationError("memory was entirely secret material; nothing stored")
        tenant_id = self._store.engagement_tenant(engagement_id)
        if not tenant_id:
            # An unscoped row can never be recalled: fail loudly instead of
            # silently losing the knowledge (P-16 keeps reads tenant-scoped).
            raise DelegationError(
                f"engagement {engagement_id} has no tenant; refusing to store "
                "memory that could never be scoped on read"
            )
        row = self._store.add_memory(
            engagement_id,
            summary.strip(),
            tenant_id=tenant_id,
            kind=kind,
        )
        return {
            "id": str(row["id"]),
            "kind": row["kind"],
            "summary": row["summary"],
            "redacted": bool(row["redacted"]),
            "redactions": replacements,
            "tenant_scoped": True,
        }

    def recall(
        self,
        engagement_id: str,
        *,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        tenant_id = self._store.engagement_tenant(engagement_id)
        if not tenant_id:
            return []
        rows = self._store.search_memory(
            tenant_id, query=query, limit=self.max_items
        )
        results = []
        for row in rows:
            if str(row.get("tenant_id") or "") != str(tenant_id):
                continue
            if not row.get("redacted"):
                continue
            results.append(
                {
                    "id": str(row["id"]),
                    "kind": row["kind"],
                    "summary": row["summary"],
                    "engagement_id": str(row["engagement_id"]),
                }
            )
        return results
