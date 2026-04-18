"""
Celery tasks for maintenance operations
"""
from celery_app import app


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
    from datetime import datetime, timedelta
    import os

    db_conn = os.getenv("DATABASE_URL")

    if not db_conn:
        return {"status": "skipped", "reason": "No DATABASE_URL configured"}

    conn = psycopg2.connect(db_conn)
    cursor = conn.cursor()

    try:
        cutoff_date = datetime.utcnow() - timedelta(days=30)

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

        conn.commit()

        return {
            "status": "completed",
            "snapshots_deleted": snapshots_deleted,
            "checkpoints_deleted": checkpoints_deleted,
            "raw_outputs_deleted": raw_outputs_deleted,
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
    from datetime import datetime, timedelta
    import os

    db_conn = os.getenv("DATABASE_URL")

    if not db_conn:
        return {"status": "skipped", "reason": "No DATABASE_URL configured"}

    conn = psycopg2.connect(db_conn)
    cursor = conn.cursor()

    try:
        cutoff_date = datetime.utcnow() - timedelta(days=7)

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
