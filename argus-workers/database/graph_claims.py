"""The one claim protocol shared by planner todos and intent nodes (A-11/A-12).

Both kinds of work in the exploration graph are claimed the same way:

* a **fencing token** minted by the database (``gen_random_uuid()``) so a write
  can prove which claim it belongs to;
* a **database-clock lease** (``NOW() + n seconds``) so an expired claim is
  reclaimable without any wall-clock agreement between processes;
* a **heartbeat** that only extends a lease while the presented token is still
  the current one;
* a **live-claim predicate** used by heartbeat and completion, so a stale worker
  cannot write as though it still owned the work.

The SQL fragments and predicates below are the single definition of that
protocol. The planner-todo path and the intent path both compose them, so a
change to expiry or fencing semantics cannot land in one and miss the other.
"""

from __future__ import annotations

from typing import Any

from database.graph_errors import GraphMutationError

#: Planner todo lease (a recon step can run for minutes).
DEFAULT_TODO_LEASE_SECONDS = 300
#: Intent lease (reference heartbeat is 15s, claim TTL 90s).
DEFAULT_INTENT_LEASE_SECONDS = 90

#: Assignment that grants a fresh lease. Takes one ``%s`` (the lease seconds).
LEASE_GRANT_SQL = (
    "lease_expires_at = NOW() + (%s * INTERVAL '1 second'), "
    "last_heartbeat_at = NOW()"
)

#: Assignment that drops a claim's fencing token and lease.
LEASE_CLEAR_SQL = "claim_token = NULL, lease_expires_at = NULL, last_heartbeat_at = NULL"


def validate_lease_seconds(lease_seconds: Any) -> int:
    """Return *lease_seconds* as a positive int or reject the claim."""
    try:
        value = int(lease_seconds)
    except (TypeError, ValueError) as exc:
        raise GraphMutationError("lease_seconds must be positive") from exc
    if value < 1:
        raise GraphMutationError("lease_seconds must be positive")
    return value


def _literal(value: str) -> str:
    """Quote an internal state name for inclusion in a predicate."""
    return "'" + str(value).replace("'", "''") + "'"


def claimable_sql(
    *,
    state_column: str = "state",
    open_states: tuple[str, ...] = ("open",),
    running_state: str = "running",
    prefix: str = "",
    lease_column: str = "lease_expires_at",
) -> str:
    """Rows a new claim may take: open work, or work whose lease expired.

    A running row with no lease at all is treated as abandoned and reclaimable;
    that is the same state a crashed claim leaves behind.
    """
    open_clause = " OR ".join(
        f"{prefix}{state_column} = {_literal(state)}" for state in open_states
    )
    return (
        f"({open_clause} OR ({prefix}{state_column} = {_literal(running_state)} "
        f"AND ({prefix}{lease_column} IS NULL "
        f"OR {prefix}{lease_column} < NOW())))"
    )


def live_claim_sql(
    *,
    state_column: str = "state",
    running_state: str = "running",
    prefix: str = "",
    claim_column: str = "claim_token",
    lease_column: str = "lease_expires_at",
) -> str:
    """The claim is current: still running, same token, lease not yet expired.

    Contains one ``%s`` placeholder for the presented claim token.
    """
    return (
        f"{prefix}{state_column} = {_literal(running_state)} "
        f"AND {prefix}{claim_column}::text = %s "
        f"AND {prefix}{lease_column} IS NOT NULL "
        f"AND {prefix}{lease_column} > NOW()"
    )


def claim_token_matches(stored_token: Any, presented_token: Any) -> bool:
    """Whether *presented_token* may act on a row holding *stored_token*.

    No stored token means the row has no live owner, so an unclaimed completion
    is legitimate; a stored token requires the exact one that was handed out.
    """
    if stored_token is None:
        return True
    if not presented_token:
        return False
    return str(stored_token) == str(presented_token)
