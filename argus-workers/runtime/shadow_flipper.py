"""
ShadowFlipper — Automatically promote feature flags from shadow mode
to default-enabled when convergence criteria are met.

Checks the DB-backed shadow stats and flips feature flags when
consecutive_successes >= CONVERGENCE_THRESHOLD for a given phase.
This eliminates the need for manual operator action to enable
shadow-validated features.

Usage:
    from runtime.shadow_flipper import check_and_auto_flip
    check_and_auto_flip("deterministic_scan")
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Map of shadow phase names → feature flag to enable when converged
SHADOW_TO_FLAG_MAP: dict[str, str] = {
    "deterministic_scan": "CLEAN_ORCHESTRATOR",
    "engagement_state": "ENGAGEMENT_STATE",
    "governance": "GOVERNANCE_V2",
}

# Threshold for auto-flip: 100 consecutive shadow matches
CONVERGENCE_THRESHOLD = 100


def check_and_auto_flip(phase: str) -> bool:
    """
    Check if a shadow phase has converged and auto-flip its flag.

    Reads the DB-backed shadow_mode_stats for the given phase.
    If consecutive_successes >= CONVERGENCE_THRESHOLD and the
    corresponding feature flag is not already enabled, writes
    it to the database as enabled.

    Args:
        phase: Shadow phase name (e.g., "deterministic_scan").

    Returns:
        True if the flag was flipped, False otherwise.
    """
    from runtime.shadow_mode import get_consecutive_successes
    from feature_flags import get_feature_flags

    consecutive = get_consecutive_successes(phase)
    if consecutive < CONVERGENCE_THRESHOLD:
        logger.debug(
            "Shadow phase '%s' not yet converged: %d/%d successes",
            phase, consecutive, CONVERGENCE_THRESHOLD,
        )
        return False

    flag_name = SHADOW_TO_FLAG_MAP.get(phase)
    if not flag_name:
        logger.warning("No feature flag mapped for shadow phase '%s'", phase)
        return False

    # Check if the flag is already enabled
    ff = get_feature_flags()
    if ff.is_enabled(flag_name):
        logger.info(
            "Flag '%s' already enabled for converged phase '%s' "
            "(%d consecutive successes)",
            flag_name, phase, consecutive,
        )
        return False

    # Write the flag to the database
    _write_flag_to_db(flag_name, True)

    logger.info(
        "AUTO-FLIP: Shadow phase '%s' converged (%d/%d consecutive successes). "
        "Feature flag '%s' set to True in database.",
        phase, consecutive, CONVERGENCE_THRESHOLD, flag_name,
    )
    return True


def _write_flag_to_db(flag_name: str, value: bool) -> None:
    """Persist a feature flag value to the database.

    Uses UPSERT so the row is created on first write and updated
    on subsequent writes.
    """
    try:
        from database.connection import db_cursor

        with db_cursor(commit=True) as cursor:
            cursor.execute(
                """
                INSERT INTO feature_flags (flag_name, enabled, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (flag_name) DO UPDATE SET
                    enabled = %s,
                    updated_at = NOW()
                """,
                (flag_name, value, value),
            )
        logger.info("Feature flag '%s' set to %s in database", flag_name, value)
    except Exception as e:
        logger.error("Failed to write feature flag '%s' to DB: %s", flag_name, e)
