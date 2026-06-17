"""
Shadow-Mode Validation — Run new + old paths in parallel, compare outputs.

Implements Principle 2 from the Agent Runtime Refactor spec:

    Before switching to any new component, run it in parallel with the old
    component and compare outputs. Shadow-mode MUST pass for 100 consecutive
    test engagements before the new path becomes the default.

Usage:
    from runtime.shadow_mode import shadow_compare

    # In the feature-flag gated code path:
    if _ff_enabled("MY_FLAG", default=False):
        new_result = new_path()
        # Shadow-compare against old path:
        shadow_compare("my_phase", engagement_id, new_result, lambda: old_path())
        return new_result
    else:
        return old_path()

The shadow comparison logs a warning on mismatch but does NOT raise an
exception — it is purely observational. Use the accumulated mismatch count
to decide when to flip the flag to True by default.
"""

import hashlib
import json
import logging
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# Thread-safe counter for tracking consecutive successes
# NOTE: threading.Lock() does NOT synchronize across Celery worker processes.
# In multi-worker deployments, these counters are per-process only.
# For cross-process synchronization, use Redis or DB-backed counters.
_counter_lock = threading.Lock()
_consecutive_successes: dict[str, int] = {}
_total_mismatches: dict[str, int] = {}


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
    are logged at WARNING level and counted for observability.

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
            phase, engagement_id, e,
        )
        with _counter_lock:
            _consecutive_successes[phase] = 0
            _total_mismatches[phase] = _total_mismatches.get(phase, 0) + 1
        return

    # Compare using hashes
    if key_fields is not None and isinstance(new_result, dict) and isinstance(old_result, dict):
        # Compare only the specified key fields
        new_subset = {k: new_result.get(k) for k in key_fields if k in new_result}
        old_subset = {k: old_result.get(k) for k in key_fields if k in old_result}
        match = _compute_hash(new_subset) == _compute_hash(old_subset)
    else:
        # Compare full results
        match = _compute_hash(new_result) == _compute_hash(old_result)

    with _counter_lock:
        if match:
            _consecutive_successes[phase] = _consecutive_successes.get(phase, 0) + 1
            logger.debug(
                "SHADOW_OK: phase=%s engagement=%s (consecutive: %d)",
                phase, engagement_id, _consecutive_successes[phase],
            )
        else:
            logger.warning(
                "SHADOW_MISMATCH: phase=%s engagement=%s — outputs differ. "
                "Consecutive successes reset to 0. Total mismatches: %d",
                phase, engagement_id, _total_mismatches.get(phase, 0) + 1,
            )
            _consecutive_successes[phase] = 0
            _total_mismatches[phase] = _total_mismatches.get(phase, 0) + 1


def get_shadow_stats(phase: str | None = None) -> dict:
    """
    Get shadow-mode validation statistics.

    Args:
        phase: Optional phase name. If None, returns all phases.

    Returns:
        Dict with consecutive_successes and total_mismatches per phase.
    """
    with _counter_lock:
        if phase:
            return {
                "phase": phase,
                "consecutive_successes": _consecutive_successes.get(phase, 0),
                "total_mismatches": _total_mismatches.get(phase, 0),
            }
        return {
            "consecutive_successes": dict(_consecutive_successes),
            "total_mismatches": dict(_total_mismatches),
        }


def reset_shadow_stats(phase: str | None = None):
    """Reset shadow-mode statistics for testing."""
    with _counter_lock:
        if phase:
            _consecutive_successes.pop(phase, None)
            _total_mismatches.pop(phase, None)
        else:
            _consecutive_successes.clear()
            _total_mismatches.clear()
