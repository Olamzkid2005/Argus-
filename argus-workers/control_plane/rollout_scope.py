"""Stage 5 per-engagement V2 allowlist (`stage5-rollout-plan.md` §2).

``ARGUS_V2_ENGAGEMENTS`` holds a comma-separated list of engagement IDs that
may run the V2 dispatcher loop. Semantics are deliberately narrow:

* unset or blank → unscoped: every engagement is eligible. This preserves the
  pre-Stage-5 behaviour (and keeps every existing conformance suite green)
  until an operator scopes a real cohort.
* set (even to values that parse to nothing) → scoped: only listed
  engagements run V2; everything else takes the legacy path. A configured but
  empty/invalid allowlist therefore denies everything — fail closed — and the
  invalid entries are logged so a typo cannot silently stall a rollout.
* comparison is case-insensitive on stripped IDs; UUIDs are not validated
  here so test/scratch engagement names keep working.

The dispatcher consults this in ``tick`` before acquiring leadership, so a
non-allowlisted engagement is left entirely alone: no lease churn, no tasks,
no cancellation.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

ENV_VAR = "ARGUS_V2_ENGAGEMENTS"


def parse_allowlist(raw: str | None) -> frozenset[str] | None:
    """Parse an allowlist value. ``None`` = unscoped (allow all)."""
    if raw is None or raw.strip() == "":
        return None
    entries = [entry.strip().lower() for entry in raw.split(",")]
    valid = frozenset(entry for entry in entries if entry)
    dropped = [entry for entry in entries if not entry]
    if dropped:
        logger.warning(
            "Ignoring %d empty entr%s in %s",
            len(dropped),
            "y" if len(dropped) == 1 else "ies",
            ENV_VAR,
        )
    if not valid:
        logger.warning(
            "%s is set but lists no usable engagement: V2 runs nowhere", ENV_VAR
        )
    return valid


def read_allowlist() -> frozenset[str] | None:
    """Read the allowlist from the environment. ``None`` = unscoped."""
    return parse_allowlist(os.getenv(ENV_VAR))


def v2_enabled_for_engagement(engagement_id: str) -> bool:
    """True when the V2 dispatcher may run for this engagement."""
    allowlist = read_allowlist()
    if allowlist is None:
        return True
    return engagement_id.strip().lower() in allowlist
