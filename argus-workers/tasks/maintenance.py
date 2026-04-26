"""
Celery tasks for maintenance operations
"""
from celery_app import app
from datetime import datetime, UTC, timedelta
import logging

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
    import psycopg2
    import os

    db_conn = os.getenv("DATABASE_URL")

    if not db_conn:
        return {"status": "skipped", "reason": "No DATABASE_URL configured"}

    conn = psycopg2.connect(db_conn)
    cursor = conn.cursor()

    try:
        cutoff_date = datetime.now(UTC) - timedelta(days=30)

        cursor.execute(
            """
            DELETE FROM decision_snapshots
            WHERE created_at < %s
            """,
            (cutoff_date,)
        )
        snapshots_deleted = cursor.rowcount

        cursor.execute(
            """
            DELETE FROM checkpoints
            WHERE created_at < %s
            """,
            (cutoff_date,)
        )
        checkpoints_deleted = cursor.rowcount

        cursor.execute(
            """
            DELETE FROM raw_outputs
            WHERE created_at < %s
            """,
            (cutoff_date,)
        )
        raw_outputs_deleted = cursor.rowcount

        cursor.execute(
            """
            DELETE FROM query_performance_log
            WHERE created_at < %s
            """,
            (cutoff_date,)
        )
        perf_logs_deleted = cursor.rowcount

        conn.commit()

        return {
            "status": "completed",
            "snapshots_deleted": snapshots_deleted,
            "checkpoints_deleted": checkpoints_deleted,
            "raw_outputs_deleted": raw_outputs_deleted,
            "perf_logs_deleted": perf_logs_deleted,
        }
    except Exception as e:
        conn.rollback()
        return {"status": "error", "error": str(e)}
    finally:
        cursor.close()
        conn.close()


@app.task(bind=True, name="tasks.maintenance.cleanup_failed_engagements")
def cleanup_failed_engagements(self):
    """
    Clean up engagements that have been in failed state for more than 7 days
    """
    import psycopg2
    import os

    db_conn = os.getenv("DATABASE_URL")

    if not db_conn:
        return {"status": "skipped", "reason": "No DATABASE_URL configured"}

    conn = psycopg2.connect(db_conn)
    cursor = conn.cursor()

    try:
        cutoff_date = datetime.now(UTC) - timedelta(days=7)

        cursor.execute(
            """
            DELETE FROM engagement_states
            WHERE engagement_id IN (
                SELECT id FROM engagements
                WHERE status = 'failed'
                AND updated_at < %s
            )
            """,
            (cutoff_date,)
        )
        states_deleted = cursor.rowcount

        cursor.execute(
            """
            DELETE FROM loop_budgets
            WHERE engagement_id IN (
                SELECT id FROM engagements
                WHERE status = 'failed'
                AND updated_at < %s
            )
            """,
            (cutoff_date,)
        )
        budgets_deleted = cursor.rowcount

        cursor.execute(
            """
            DELETE FROM engagements
            WHERE status = 'failed'
            AND updated_at < %s
            """,
            (cutoff_date,)
        )
        engagements_deleted = cursor.rowcount

        conn.commit()

        return {
            "status": "completed",
            "engagements_deleted": engagements_deleted,
            "states_deleted": states_deleted,
            "budgets_deleted": budgets_deleted,
        }
    except Exception as e:
        conn.rollback()
        return {"status": "error", "error": str(e)}
    finally:
        cursor.close()
        conn.close()


@app.task(bind=True, name="tasks.maintenance.cleanup_checkpoints")
def cleanup_checkpoints(self):
    """Clean up old checkpoints using CheckpointManager"""
    import os
    from checkpoint_manager import CheckpointManager

    db_conn = os.getenv("DATABASE_URL")
    if not db_conn:
        return {"status": "skipped", "reason": "No DATABASE_URL configured"}

    try:
        manager = CheckpointManager(db_conn)
        deleted = manager.cleanup_old_checkpoints(max_age_days=7)
        return {"status": "completed", "checkpoints_deleted": deleted}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.task(bind=True, name="tasks.maintenance.refresh_views")
def refresh_views(self):
    """Refresh materialized views for query performance"""
    import psycopg2
    import os

    db_conn = os.getenv("DATABASE_URL")
    if not db_conn:
        return {"status": "skipped", "reason": "No DATABASE_URL configured"}

    conn = psycopg2.connect(db_conn)
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT refresh_mv_org_dashboard()")
        cursor.execute("SELECT refresh_mv_engagement_findings()")
        cursor.execute("SELECT refresh_mv_tool_performance()")
        conn.commit()

        return {"status": "completed", "views_refreshed": 3}
    except Exception as e:
        conn.rollback()
        return {"status": "error", "error": str(e)}
    finally:
        cursor.close()
        conn.close()


@app.task(bind=True, name="tasks.maintenance.worker_health_check")
def worker_health_check(self):
    """Check worker health and cleanup dead workers"""
    from health_monitor import get_health_monitor

    try:
        monitor = get_health_monitor()
        unhealthy = monitor.get_unhealthy_workers()
        cleaned = monitor.cleanup_dead_workers()

        if unhealthy:
            logger.warning(f"Found {len(unhealthy)} unhealthy workers")

        return {
            "status": "completed",
            "unhealthy_workers": len(unhealthy),
            "cleaned_workers": cleaned,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}
