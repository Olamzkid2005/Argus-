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


# ---------------------------------------------------------------------------
# Materialized-view refresh (migration 007)
# ---------------------------------------------------------------------------
# All three views have unique indexes, so CONCURRENTLY refresh is safe.
_MATERIALIZED_VIEWS = (
    "mv_org_dashboard",
    "mv_engagement_findings",
    "mv_tool_performance",
)


@app.task(bind=True, name="tasks.maintenance.refresh_views")
def refresh_views(self):
    """
    Refresh materialized views used by dashboard and reporting queries.

    Runs every 5 minutes via Celery Beat.  Uses ``CONCURRENTLY`` so that
    queries against the views are never blocked.  Each view must have a
    unique index (created in migration 007).

    Note: ``REFRESH MATERIALIZED VIEW CONCURRENTLY`` cannot run inside a
    transaction block, so the connection is switched to autocommit for the
    duration of the refresh.
    """
    refreshed: list[str] = []
    errors: list[dict[str, str]] = []
    try:
        from database.connection import get_db

        db = get_db()
        conn = db.get_connection()
        try:
            # CONCURRENTLY refresh must not be inside a transaction.
            conn.autocommit = True
            cursor = conn.cursor()
            try:
                for view_name in _MATERIALIZED_VIEWS:
                    try:
                        cursor.execute(
                            f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view_name}"
                        )
                        refreshed.append(view_name)
                    except Exception as exc:
                        logger.warning(
                            "Failed to refresh view %s: %s", view_name, exc
                        )
                        errors.append({"view": view_name, "error": str(exc)})
            finally:
                cursor.close()
        finally:
            conn.autocommit = False
            db.release_connection(conn)

        return {
            "status": "completed",
            "refreshed": refreshed,
            "errors": errors,
        }
    except Exception as e:
        logger.error("refresh_views failed: %s", e)
        return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# Nuclei template updater (daily)
# ---------------------------------------------------------------------------


@app.task(bind=True, name="tasks.maintenance.update_nuclei_templates")
def update_nuclei_templates(self, timeout: int = 120):
    """
    Update the local nuclei template cache so new CVEs are detected.

    Runs daily via Celery Beat.  Wraps
    ``tools.update_nuclei_templates.update_nuclei_templates``.
    """
    try:
        from tools.update_nuclei_templates import (
            get_template_count,
        )
        from tools.update_nuclei_templates import (
            update_nuclei_templates as _do_update,
        )

        before = get_template_count()
        success = _do_update(timeout=timeout)
        after = get_template_count()
        return {
            "status": "completed",
            "success": success,
            "templates_before": before,
            "templates_after": after,
        }
    except Exception as e:
        logger.error("update_nuclei_templates task failed: %s", e)
        return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# Dead-Letter-Queue cleanup (every 12 h)
# ---------------------------------------------------------------------------


@app.task(bind=True, name="tasks.maintenance.cleanup_dlq")
def cleanup_dlq(self, older_than_hours: int = 168):
    """
    Purge stale entries from the Dead Letter Queue.

    Runs every 12 hours via Celery Beat.  Removes DLQ entries older than
    the retention window (default 7 days / 168 hours) so the queue stays
    bounded.  Redis TTL handles the sorted sets; this sweep also cleans
    up the per-engagement indexes and the hash data store.
    """
    try:
        from dead_letter_queue import get_dlq

        purged = get_dlq().purge(older_than_hours=older_than_hours)
        logger.info(
            "DLQ cleanup: purged %d entries older than %dh",
            purged,
            older_than_hours,
        )
        return {
            "status": "completed",
            "purged": purged,
            "older_than_hours": older_than_hours,
        }
    except Exception as e:
        logger.error("cleanup_dlq failed: %s", e)
        return {"status": "error", "error": str(e)}
