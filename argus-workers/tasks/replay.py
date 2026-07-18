"""
Celery task for replaying failed tasks from the Dead Letter Queue.

Keeps the Celery dependency out of dead_letter_queue.py,
breaking the circular import between celery_app and dead_letter_queue.

Blocker 8 fix: Adds autonomous replay strategy that periodically scans
all DLQ entries and replays eligible tasks with adaptive parameters.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from celery_app import app
from dead_letter_queue import get_dlq
from tool_core._compat import utc

logger = logging.getLogger(__name__)


# ── Eligibility thresholds ──
_ELIGIBILITY_MIN_AGE_SECONDS = 600  # 10 min before first replay attempt
_MAX_AUTO_REPLAYS = 2  # Max times a task will be auto-replayed
_MAX_PER_ENGAGEMENT = 2  # Max tasks replayed per engagement per cycle


@app.task(bind=True, name="tasks.replay.replay_dlq_task")
def replay_dlq_task(self, task_id: str) -> bool:
    """
    Find a failed task in the DLQ and re-dispatch it to Celery.

    Args:
        task_id: The task ID to replay

    Returns:
        True if replay initiated successfully
    """
    dlq = get_dlq()
    task_data = dlq.get_task_by_id(task_id)
    if not task_data:
        logger.warning("Task %s not found in DLQ", task_id)
        return False

    try:
        app.send_task(
            task_data["task_name"],
            args=task_data["args"],
            kwargs=task_data["kwargs"],
            task_id=task_id,
        )
        logger.info("Replayed task %s", task_id)
        return True
    except Exception as e:
        logger.error("Failed to replay task %s: %s", task_id, e)
        return False


@app.task(bind=True, name="tasks.replay.replay_eligible_dlq_tasks")
def replay_eligible_dlq_tasks(self):
    """
    Autonomous DLQ replay strategy.

    Blocker 8 fix: Periodically scans ALL DLQ entries and replays tasks
    that meet eligibility criteria. Prevents infinite re-replay loops
    with replay count tracking and per-engagement rate limiting.

    Eligibility:
    - Task was added to DLQ at least 10 minutes ago (system stabilization)
    - Task has been auto-replayed fewer than 2 times
    - No more than 2 tasks from the same engagement are replayed per cycle

    Strategy adaptation:
    - Timeout-failed tasks get a longer countdown
    - Connection-failed tasks get a moderate countdown
    - Other failures get a short countdown

    Returns:
        dict with summary of replays attempted.
    """
    dlq = get_dlq()
    all_tasks = dlq.get_all_failed_tasks(limit=200)

    if not all_tasks:
        logger.info("DLQ replay: no tasks found in DLQ — nothing to replay")
        return {"scanned": 0, "replayed": 0, "skipped": 0}
    
    now = datetime.now(utc).timestamp()
    replayed: list[str] = []
    skipped: list[dict[str, Any]] = []
    engagement_counts: dict[str, int] = {}

    for task_data in all_tasks:
        task_id = task_data.get("task_id", "")
        if not task_id:
            continue

        # ── Check replay count ──
        replay_count = dlq.get_replay_count(task_id)
        if replay_count >= _MAX_AUTO_REPLAYS:
            skipped.append({
                "task_id": task_id,
                "reason": f"max_replays_exceeded ({replay_count}/{_MAX_AUTO_REPLAYS})",
            })
            continue

        # ── Check minimum age (must be in DLQ for at least 10 min) ──
        failed_at_str = task_data.get("failed_at", "")
        age_seconds = 0
        if failed_at_str:
            try:
                failed_dt = datetime.fromisoformat(failed_at_str)
                if failed_dt.tzinfo is None:
                    failed_dt = failed_dt.replace(tzinfo=utc)
                age_seconds = (now - failed_dt.timestamp())
            except (ValueError, TypeError):
                age_seconds = _ELIGIBILITY_MIN_AGE_SECONDS + 1  # allow if unparseable

        if age_seconds < _ELIGIBILITY_MIN_AGE_SECONDS:
            skipped.append({
                "task_id": task_id,
                "reason": f"too_young ({int(age_seconds)}s < {_ELIGIBILITY_MIN_AGE_SECONDS}s)",
            })
            continue

        # ── Per-engagement rate limiting ──
        engagement_id = task_data.get("engagement_id", "")
        if engagement_id:
            eng_count = engagement_counts.get(engagement_id, 0)
            if eng_count >= _MAX_PER_ENGAGEMENT:
                skipped.append({
                    "task_id": task_id,
                    "reason": f"engagement_rate_limit ({engagement_id} already at {eng_count})",
                })
                continue
            engagement_counts[engagement_id] = eng_count + 1

        # ── Calculate adaptive countdown based on error type ──
        error_msg = (task_data.get("error_message", "") or "").lower()
        error_class = (task_data.get("error_class", "") or "").lower()

        if "timeout" in error_msg or "time limit" in error_msg or "soft time" in error_msg:
            countdown = 300  # 5 min — give system time to recover
        elif "connection" in error_msg or "refused" in error_msg or "unavailable" in error_msg:
            countdown = 60   # 1 min — transient network issue
        else:
            countdown = 30   # 30 sec — generic transient

        # ── Replay the task ──
        try:
            task_name = task_data.get("task_name", "")
            task_args = task_data.get("args", [])
            task_kwargs = task_data.get("kwargs", {})

            # Increment replay count BEFORE sending so the count is accurate
            # even if the send_task call fails or is interrupted.
            new_count = dlq.increment_replay_count(task_id)

            app.send_task(
                task_name,
                args=task_args,
                kwargs=task_kwargs,
                task_id=task_id,
                countdown=countdown,
            )
            replayed.append(task_id)
            logger.info(
                "DLQ replay: %s (%s) — countdown=%ds, replay #%d",
                task_id, task_name, countdown, new_count,
            )
        except Exception as e:
            logger.error(
                "DLQ replay FAILED for task %s: %s", task_id, e,
            )
            skipped.append({
                "task_id": task_id,
                "reason": f"replay_error: {e}",
            })

    result = {
        "scanned": len(all_tasks),
        "replayed": len(replayed),
        "skipped": len(skipped),
        "replayed_ids": replayed[:20],  # truncate for log readability
        "skipped_details": skipped[:20],
    }

    if replayed:
        logger.info(
            "DLQ replay: %d/%d replayed, %d skipped — %s",
            len(replayed), len(all_tasks), len(skipped),
            [t[:12] for t in replayed[:10]],
        )
    else:
        logger.debug(
            "DLQ replay: 0/%d replayed (%d skipped) — no eligible tasks",
            len(all_tasks), len(skipped),
        )

    return result
