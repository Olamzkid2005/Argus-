"""
Celery tasks for maintenance operations

Uses shared ConnectionManager for database access (H-23).
"""

import logging
from datetime import datetime, timedelta

from celery_app import app
from database.connection import db_cursor
from tool_core._compat import utc

logger = logging.getLogger(__name__)


@app.task(bind=True, name="tasks.maintenance.cleanup_old_results")
def cleanup_old_results(self):
    """
    Clean up old task results and expired data

    This task runs periodically to:
    - Remove expired Celery results
    - Clean up old decision snapshots
    - Clean up old checkpoints
    """
    try:
        cutoff_date = datetime.now(utc) - timedelta(days=30)

        with db_cursor(commit=True) as cursor:
            cursor.execute(
                "DELETE FROM decision_snapshots WHERE created_at < %s", (cutoff_date,)
            )
            snapshots_deleted = cursor.rowcount

            cursor.execute(
                "DELETE FROM checkpoints WHERE created_at < %s", (cutoff_date,)
            )
            checkpoints_deleted = cursor.rowcount

            cursor.execute(
                "DELETE FROM raw_outputs WHERE created_at < %s", (cutoff_date,)
            )
            raw_outputs_deleted = cursor.rowcount

            cursor.execute(
                "DELETE FROM query_performance_log WHERE created_at < %s",
                (cutoff_date,),
            )
            perf_logs_deleted = cursor.rowcount

        return {
            "status": "completed",
            "snapshots_deleted": snapshots_deleted,
            "checkpoints_deleted": checkpoints_deleted,
            "raw_outputs_deleted": raw_outputs_deleted,
            "perf_logs_deleted": perf_logs_deleted,
        }
    except Exception as e:
        logger.error("cleanup_old_results failed: %s", e)
        return {"status": "error", "error": str(e)}


@app.task(bind=True, name="tasks.maintenance.cleanup_failed_engagements")
def cleanup_failed_engagements(self):
    """
    Clean up engagements that have been in failed state for more than 7 days
    """
    try:
        cutoff_date = datetime.now(utc) - timedelta(days=7)

        with db_cursor(commit=True) as cursor:
            cursor.execute(
                """DELETE FROM engagement_states
                 WHERE engagement_id IN (
                     SELECT id FROM engagements
                     WHERE status = 'failed'
                     AND updated_at < %s
                 )""",
                (cutoff_date,),
            )
            states_deleted = cursor.rowcount

            cursor.execute(
                """DELETE FROM loop_budgets
                 WHERE engagement_id IN (
                     SELECT id FROM engagements
                     WHERE status = 'failed'
                     AND updated_at < %s
                 )""",
                (cutoff_date,),
            )
            budgets_deleted = cursor.rowcount

            cursor.execute(
                """DELETE FROM scanner_activities
                 WHERE engagement_id IN (
                     SELECT id FROM engagements
                     WHERE status = 'failed'
                     AND updated_at < %s
                 )""",
                (cutoff_date,),
            )
            activities_deleted = cursor.rowcount

            cursor.execute(
                """DELETE FROM findings
                 WHERE engagement_id IN (
                     SELECT id FROM engagements
                     WHERE status = 'failed'
                     AND updated_at < %s
                 )""",
                (cutoff_date,),
            )
            findings_deleted = cursor.rowcount

            cursor.execute(
                "DELETE FROM engagements WHERE status = 'failed' AND updated_at < %s",
                (cutoff_date,),
            )
            engagements_deleted = cursor.rowcount

        return {
            "status": "completed",
            "states_deleted": states_deleted,
            "budgets_deleted": budgets_deleted,
            "activities_deleted": activities_deleted,
            "findings_deleted": findings_deleted,
            "engagements_deleted": engagements_deleted,
        }
    except Exception as e:
        logger.error("cleanup_failed_engagements failed: %s", e)
        return {"status": "error", "error": str(e)}


@app.task(bind=True, name="tasks.maintenance.cleanup_checkpoints")
def cleanup_checkpoints(self):
    """
    Clean up old checkpoints based on retention policy
    """
    try:
        # Keep 90 days of checkpoints for active engagements,
        # 30 days for completed/failed
        cutoff_active = datetime.now(utc) - timedelta(days=90)
        cutoff_completed = datetime.now(utc) - timedelta(days=30)

        with db_cursor(commit=True) as cursor:
            # Delete old checkpoints for active engagements
            cursor.execute(
                """DELETE FROM checkpoints
                 WHERE created_at < %s
                 AND engagement_id IN (
                     SELECT id FROM engagements WHERE status IN ('running', 'pending')
                 )""",
                (cutoff_active,),
            )
            active_deleted = cursor.rowcount

            # Delete old checkpoints for completed/failed engagements
            cursor.execute(
                """DELETE FROM checkpoints
                 WHERE created_at < %s
                 AND engagement_id IN (
                     SELECT id FROM engagements WHERE status IN ('completed', 'failed', 'cancelled')
                 )""",
                (cutoff_completed,),
            )
            completed_deleted = cursor.rowcount

        return {
            "status": "completed",
            "active_engagement_checkpoints_deleted": active_deleted,
            "completed_engagement_checkpoints_deleted": completed_deleted,
        }
    except Exception as e:
        logger.error("cleanup_checkpoints failed: %s", e)
        return {"status": "error", "error": str(e)}


@app.task(bind=True, name="tasks.maintenance.check_shadow_convergence")
def check_shadow_convergence(self):
    """
    Check shadow-mode convergence for all tracked phases and auto-flip
    feature flags when convergence criteria are met.

    This task is invoked by Celery Beat every 5 minutes. For each phase
    in the shadow-to-flag mapping, it checks if consecutive_successes
    >= CONVERGENCE_THRESHOLD (100). If so, the corresponding feature flag
    is set to True in the database, enabling the feature permanently.
    """
    try:
        from runtime.shadow_flipper import SHADOW_TO_FLAG_MAP, check_and_auto_flip

        flipped = []
        for phase in SHADOW_TO_FLAG_MAP:
            if check_and_auto_flip(phase):
                flipped.append(phase)

        if flipped:
            logger.info(
                "Shadow convergence check: auto-flipped %d phase(s): %s",
                len(flipped), ", ".join(flipped),
            )
        else:
            logger.debug("Shadow convergence check: no phases ready for flip")

        return {
            "status": "ok",
            "phases_checked": list(SHADOW_TO_FLAG_MAP.keys()),
            "phases_flipped": flipped,
        }
    except Exception as e:
        logger.error("check_shadow_convergence failed: %s", e)
        return {"status": "error", "error": str(e)}


@app.task(bind=True, name="tasks.maintenance.worker_health_check")
def worker_health_check(self):
    """
    Periodic health check to verify Celery workers are responsive.

    This task is invoked by Celery Beat every 60 seconds. If the worker
    fails to process it (e.g., stuck or crashed), the beat scheduler
    will detect the missed heartbeat and alert.
    """
    import socket

    now = datetime.now(utc)
    return {
        "status": "ok",
        "hostname": socket.gethostname(),
        "timestamp": now.isoformat(),
    }
