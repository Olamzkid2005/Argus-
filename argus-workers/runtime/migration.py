"""
In-Flight Engagement Migration — SQL-level, gated by feature-flag + timestamp.

The refactor spec requires that in-flight engagements (those created before a
rollout timestamp) continue on the old code path while new engagements use the
new EngagementState format. This module provides safe, idempotent migration
utilities implementing that pattern.

Migration Gate Logic:
    1. If ENGAGEMENT_STATE flag is OFF → no migration (all engagements old path)
    2. If engagement.created_at < rollout_timestamp → skip (in-flight, old path)
    3. If engagement.created_at >= rollout_timestamp → migrate (new path)
    4. Always safe to call multiple times (idempotent)

Rollout timestamp is configured via:
    - Environment variable: ARGUS_FF_ROLLOUT_TIMESTAMP (ISO 8601)
    - If unset, ALL engagements are eligible (immediate rollout).
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from tool_core._compat import UTC

logger = logging.getLogger(__name__)

# ── Rollout timestamp resolution ──

_ROLLOUT_TIMESTAMP_CACHE: datetime | None = None


def _get_rollout_timestamp() -> datetime | None:
    """Get the rollout timestamp from environment.

    Returns:
        datetime in UTC, or None if unset (all engagements eligible).
    """
    global _ROLLOUT_TIMESTAMP_CACHE
    if _ROLLOUT_TIMESTAMP_CACHE is not None:
        return _ROLLOUT_TIMESTAMP_CACHE
    raw = os.environ.get("ARGUS_FF_ROLLOUT_TIMESTAMP")
    if raw:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            _ROLLOUT_TIMESTAMP_CACHE = dt
            return dt
        except ValueError:
            logger.warning("Invalid ARGUS_FF_ROLLOUT_TIMESTAMP=%r — ignoring", raw)
    _ROLLOUT_TIMESTAMP_CACHE = None
    return None


def _clear_rollout_cache():
    """Clear cached rollout timestamp (for testing)."""
    global _ROLLOUT_TIMESTAMP_CACHE
    _ROLLOUT_TIMESTAMP_CACHE = None


# ── Migration result ──


@dataclass
class MigrateResult:
    """Result of an engagement migration attempt."""

    engagement_id: str
    status: str  # "migrated" | "skipped" | "already_live" | "error"
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)


# ── Table DDL ──

# M-v4-13/M-v4-14: Renamed from 'decision_snapshots' to avoid collision with
# schema.sql which defines a different table with the same name.
# Uses UUID PKs with defaults instead of bare TEXT PKs.
_DECISION_SNAPSHOTS_DDL = """
CREATE TABLE IF NOT EXISTS agent_decision_log (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    engagement_id   UUID NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
    action_id       UUID NOT NULL,
    observation_hash TEXT NOT NULL,
    reasoning_hash  TEXT NOT NULL,
    selected_tool   TEXT NOT NULL,
    arguments       JSONB,
    tool_cost_usd   NUMERIC(10,4) DEFAULT 0,
    state_version   INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    execution_success BOOLEAN,
    execution_error TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_decision_log_engagement
    ON agent_decision_log (engagement_id);
CREATE INDEX IF NOT EXISTS idx_agent_decision_log_action
    ON agent_decision_log (action_id);
"""

# M-v4-13/M-v4-14: Renamed from 'engagement_state_snapshots' to avoid collision.
# Uses UUID PK with default generation.
_ENGAGEMENT_STATE_SNAPSHOTS_DDL = """
CREATE TABLE IF NOT EXISTS agent_state_log (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    engagement_id   UUID NOT NULL UNIQUE REFERENCES engagements(id) ON DELETE CASCADE,
    state_version   INTEGER NOT NULL DEFAULT 0,
    snapshot_data   JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agent_state_log_eid
    ON agent_state_log (engagement_id);
"""


def ensure_tables() -> bool:
    """Create the required tables if they don't exist (idempotent).

    Safe to call multiple times — uses CREATE TABLE IF NOT EXISTS.

    Returns:
        True if tables were created or already exist, False on error.
    """
    try:
        from database.connection import db_cursor

        with db_cursor(commit=True) as cursor:
            cursor.execute(_DECISION_SNAPSHOTS_DDL)
            cursor.execute(_ENGAGEMENT_STATE_SNAPSHOTS_DDL)
        logger.info("Migration tables verified/created")
        return True
    except Exception as e:
        logger.error("Failed to ensure migration tables: %s", e)
        return False


# ── Engagement query ──


def _get_engagement_created_at(engagement_id: str) -> datetime | None:
    """Query the engagement's created_at timestamp.

    Returns:
        UTC datetime, or None if the engagement is not found.
    """
    try:
        from database.connection import db_cursor

        with db_cursor() as cursor:
            cursor.execute(
                "SELECT created_at FROM engagements WHERE id = %s",
                (engagement_id,),
            )
            row = cursor.fetchone()
            if row:
                dt = row[0]
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return dt
        return None
    except Exception as e:
        logger.warning("Failed to query engagement %s: %s", engagement_id, e)
        return None


def _engagement_has_state_snapshot(engagement_id: str) -> bool:
    """Check if an engagement already has a state snapshot (already migrated)."""
    try:
        from database.connection import db_cursor

        with db_cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM agent_state_log WHERE engagement_id = %s",
                (engagement_id,),
            )
            return cursor.fetchone() is not None
    except Exception:
        logger.debug(
            "Failed to check state snapshot for %s", engagement_id, exc_info=True
        )
        return False


# ── In-flight migration logic ──


def migrate_engagement(
    engagement_id: str,
    created_at: datetime | None = None,
    force: bool = False,
) -> MigrateResult:
    """Determine whether an engagement should use the new or old state path.

    The migration logic is:
        1. If ENGAGEMENT_STATE flag is OFF → skip (old path).
        2. If engagement already has a state snapshot → already_live.
        3. If force=True and engaged created_at >= rollout → migrate.
        4. If created_at < rollout_timestamp → skip (in-flight, old path).
        5. Otherwise → migrate (new path).

    This function is observational — it returns a result dict but does NOT
    permanently alter engagement data unless migration logic is added to
    write the initial snapshot.

    Args:
        engagement_id: The engagement to evaluate.
        created_at: Pre-fetched created_at (avoids extra DB query if known).
        force: Force migration regardless of timestamp gate.

    Returns:
        MigrateResult with status and reasoning.
    """
    from feature_flags import is_enabled as _ff_enabled

    # Step 1: Check feature flag
    if not force and not _ff_enabled("ENGAGEMENT_STATE", default=False):
        return MigrateResult(
            engagement_id=engagement_id,
            status="skipped",
            reason="ENGAGEMENT_STATE feature flag is disabled",
        )

    # Step 2: Check if already migrated
    if _engagement_has_state_snapshot(engagement_id):
        return MigrateResult(
            engagement_id=engagement_id,
            status="already_live",
            reason="Engagement already has a state snapshot",
        )

    # Step 3: Resolve created_at
    if created_at is None:
        created_at = _get_engagement_created_at(engagement_id)
    if created_at is None:
        return MigrateResult(
            engagement_id=engagement_id,
            status="error",
            reason="Engagement not found in database",
        )

    # Step 4: Normalize created_at to UTC-aware for comparison
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    rollout_ts = None
    if not force:
        rollout_ts = _get_rollout_timestamp()
        if rollout_ts is not None and created_at < rollout_ts:
            return MigrateResult(
                engagement_id=engagement_id,
                status="skipped",
                reason=(
                    f"Engagement created {created_at.isoformat()} is before "
                    f"rollout timestamp {rollout_ts.isoformat()} "
                    f"— keeping on old path for in-flight safety"
                ),
                details={
                    "created_at": created_at.isoformat(),
                    "rollout_timestamp": rollout_ts.isoformat(),
                },
            )

    # Step 5: Eligible for migration
    return MigrateResult(
        engagement_id=engagement_id,
        status="migrated",
        reason="Engagement eligible for EngagementState path",
        details={
            "created_at": created_at.isoformat(),
            "rollout_timestamp": rollout_ts.isoformat() if rollout_ts else None,
        },
    )


def batch_migrate_pending_engagements(
    limit: int = 100,
    status_filter: str | None = None,
    force: bool = False,
) -> list[MigrateResult]:
    """Evaluate all engagements and return migration results for eligible ones.

    This is the bulk entry point — iterates engagements in the database and
    applies the migration gate logic to each.

    Args:
        limit: Max engagements to evaluate (default 100).
        status_filter: Optional status filter (e.g. "created", "scanning").
                       If None, evaluates all non-terminal engagements.
        force: Force migration regardless of timestamp.

    Returns:
        List of MigrateResult for each evaluated engagement.
    """
    if not ensure_tables():
        logger.error("Cannot batch migrate — tables missing")
        return []

    results: list[MigrateResult] = []

    try:
        from database.connection import db_cursor

        with db_cursor() as cursor:
            if status_filter:
                cursor.execute(
                    "SELECT id, created_at FROM engagements "
                    "WHERE status = %s ORDER BY created_at ASC LIMIT %s",
                    (status_filter, limit),
                )
            else:
                cursor.execute(
                    "SELECT id, created_at FROM engagements "
                    "WHERE status NOT IN ('complete', 'failed') "
                    "ORDER BY created_at ASC LIMIT %s",
                    (limit,),
                )

            rows = cursor.fetchall()
    except Exception as e:
        logger.error("Failed to query engagements for batch migration: %s", e)
        return results

    for row in rows:
        eid, created_at = row
        if created_at and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        result = migrate_engagement(eid, created_at=created_at, force=force)
        results.append(result)

    migrated = sum(1 for r in results if r.status == "migrated")
    skipped = sum(1 for r in results if r.status in ("skipped", "already_live"))
    errors = sum(1 for r in results if r.status == "error")
    logger.info(
        "Batch migration: %d evaluated, %d migrated, %d skipped, %d errors",
        len(results),
        migrated,
        skipped,
        errors,
    )

    return results


def get_migration_status() -> dict[str, Any]:
    """Get the current migration configuration status for observability.

    Returns:
        Dict with rollout config and migration table status.
    """
    rollout_ts = _get_rollout_timestamp()
    tables_ok = False
    engagement_count = 0
    migrated_count = 0

    try:
        from database.connection import db_cursor

        with db_cursor() as cursor:
            # Check if tables exist
            cursor.execute(
                "SELECT EXISTS (SELECT FROM information_schema.tables "
                "WHERE table_name = 'agent_state_log')"
            )
            tables_ok = cursor.fetchone()[0]

            if tables_ok:
                cursor.execute("SELECT COUNT(*) FROM engagements")
                engagement_count = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM agent_state_log")
                migrated_count = cursor.fetchone()[0]
    except Exception as e:
        logger.warning("Failed to query migration status: %s", e)

    return {
        "rollout_timestamp": rollout_ts.isoformat() if rollout_ts else None,
        "rollout_env_var": "ARGUS_FF_ROLLOUT_TIMESTAMP",
        "tables_created": tables_ok,
        "total_engagements": engagement_count,
        "migrated_engagements": migrated_count,
        "pending_migration": max(0, engagement_count - migrated_count),
    }
