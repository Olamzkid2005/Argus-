"""
Shadow-Mode Validation — DB-backed counters for cross-worker convergence.

Replaces per-process threading.Lock() counters with PostgreSQL atomic
UPDATE operations. This ensures shadow stats converge across all Celery
workers, enabling the "100 consecutive successes" requirement.

Usage:
    from runtime.shadow_mode import shadow_compare, get_shadow_stats

    # In the feature-flag gated code path:
    if _ff_enabled("MY_FLAG", default=False):
        new_result = new_path()
        shadow_compare("my_phase", engagement_id, new_result, lambda: old_path())
        return new_result
    else:
        return old_path()

The shadow comparison logs a warning on mismatch but does NOT raise an
exception — it is purely observational. Use get_shadow_stats() to check
accumulated convergence data.
"""

import hashlib
import json
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def _normalize_for_comparison(obj: Any) -> str:
    """Normalize an object to a stable string for comparison.

    Handles dicts, lists, and primitive types. Sorts keys for stability.
    """
    try:
        if isinstance(obj, (dict, list)):
            return json.dumps(obj, sort_keys=True, default=str)
        elif hasattr(obj, "to_dict"):
            return json.dumps(obj.to_dict(), sort_keys=True, default=str)
        elif hasattr(obj, "__dict__"):
            return json.dumps(obj.__dict__, sort_keys=True, default=str)
        else:
            return str(obj)
    except (TypeError, ValueError):
        return str(obj)


def _compute_hash(obj: Any) -> str:
    """Compute a stable hash for comparison purposes."""
    normalized = _normalize_for_comparison(obj)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _update_stats_db(phase: str, match: bool) -> None:
    """Atomically update shadow stats in Postgres.

    On match:   consecutive_successes += 1
    On mismatch: consecutive_successes = 0, total_mismatches += 1

    Uses a single atomic UPSERT to prevent race conditions across workers.
    The row is created on first call for a given phase.
    """
    try:
        from database.connection import db_cursor

        with db_cursor(commit=True) as cursor:
            if match:
                cursor.execute(
                    """
                    INSERT INTO shadow_mode_stats
                        (phase, consecutive_successes, total_mismatches,
                         last_run_at, last_result, updated_at)
                    VALUES (%s, 1, 0, NOW(), 'match', NOW())
                    ON CONFLICT (phase) DO UPDATE SET
                        consecutive_successes = shadow_mode_stats.consecutive_successes + 1,
                        last_run_at = NOW(),
                        last_result = 'match',
                        updated_at = NOW()
                    """,
                    (phase,),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO shadow_mode_stats
                        (phase, consecutive_successes, total_mismatches,
                         last_run_at, last_result, updated_at)
                    VALUES (%s, 0, 1, NOW(), 'mismatch', NOW())
                    ON CONFLICT (phase) DO UPDATE SET
                        consecutive_successes = 0,
                        total_mismatches = shadow_mode_stats.total_mismatches + 1,
                        last_run_at = NOW(),
                        last_result = 'mismatch',
                        updated_at = NOW()
                    """,
                    (phase,),
                )
    except Exception as e:
        logger.error("Failed to update shadow stats in DB: %s", e)


def shadow_compare(
    phase: str,
    engagement_id: str,
    new_result: Any,
    old_path_fn: Callable[[], Any],
    key_fields: list[str] | None = None,
) -> None:
    """
    Run shadow comparison: compute old_path output and compare with new_result.

    This function MUST NOT raise — it is purely observational. Mismatches
    are logged at WARNING level and counted in the DB for observability.

    Args:
        phase: Phase name for logging (e.g., "engagement_state", "deterministic_scan")
        engagement_id: Engagement ID for logging
        new_result: Result from the new code path
        old_path_fn: Callable that produces the old code path result
        key_fields: Optional list of dict keys to compare (if None, compare all)
    """
    try:
        old_result = old_path_fn()
    except Exception as e:
        logger.warning(
            "SHADOW_MISMATCH: phase=%s engagement=%s — old path raised: %s",
            phase,
            engagement_id,
            e,
        )
        _update_stats_db(phase, match=False)
        return

    # Compare using hashes
    if (
        key_fields is not None
        and isinstance(new_result, dict)
        and isinstance(old_result, dict)
    ):
        # Compare only the specified key fields
        new_subset = {k: new_result.get(k) for k in key_fields if k in new_result}
        old_subset = {k: old_result.get(k) for k in key_fields if k in old_result}
        match = _compute_hash(new_subset) == _compute_hash(old_subset)
    else:
        # Compare full results
        match = _compute_hash(new_result) == _compute_hash(old_result)

    _update_stats_db(phase, match=match)

    if match:
        logger.debug(
            "SHADOW_OK: phase=%s engagement=%s", phase, engagement_id
        )
    else:
        logger.warning(
            "SHADOW_MISMATCH: phase=%s engagement=%s — outputs differ. "
            "Consecutive successes reset to 0.",
            phase,
            engagement_id,
        )


def get_shadow_stats(phase: str | None = None) -> dict:
    """Get shadow-mode validation statistics from the database.

    Args:
        phase: Optional phase name. If None, returns all phases.

    Returns:
        Dict with stats per phase, or for a single phase when specified.
    """
    try:
        from database.connection import db_cursor

        with db_cursor() as cursor:
            if phase:
                cursor.execute(
                    "SELECT * FROM shadow_mode_stats WHERE phase = %s",
                    (phase,),
                )
                columns = [desc[0] for desc in cursor.description]
                row = cursor.fetchone()
                if row:
                    return dict(zip(columns, row, strict=False))
                return {
                    "phase": phase,
                    "consecutive_successes": 0,
                    "total_mismatches": 0,
                    "last_result": "none",
                }
            else:
                cursor.execute(
                    "SELECT * FROM shadow_mode_stats ORDER BY phase"
                )
                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()
                results: dict[str, dict] = {}
                for row in rows:
                    results[str(row[0])] = dict(zip(columns, row, strict=False))
                return results
    except Exception as e:
        logger.error("Failed to read shadow stats from DB: %s", e)
        return {"error": str(e)}


def get_consecutive_successes(phase: str) -> int:
    """Quick accessor for the consecutive successes counter.

    Args:
        phase: Shadow phase name.

    Returns:
        Number of consecutive successful comparisons (0 if no stats yet).
    """
    stats = get_shadow_stats(phase)
    if isinstance(stats, dict):
        return stats.get("consecutive_successes", 0)
    return 0


def reset_shadow_stats(phase: str | None = None):
    """Reset shadow-mode statistics (for testing).

    Args:
        phase: Optional phase name. If None, resets all phases.
    """
    try:
        from database.connection import db_cursor

        with db_cursor(commit=True) as cursor:
            if phase:
                cursor.execute(
                    "DELETE FROM shadow_mode_stats WHERE phase = %s",
                    (phase,),
                )
            else:
                cursor.execute("DELETE FROM shadow_mode_stats")
    except Exception as e:
        logger.error("Failed to reset shadow stats: %s", e)
