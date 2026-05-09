"""
Scheduled Engagements — Celery Beat task for recurring scans.

Runs every 5 minutes. Finds scheduled engagements that are due to run,
creates real engagements for them, and dispatches recon tasks.

Requirements: Scheduled engagements table (migration 032)
"""

import logging
import os
import uuid

from celery_app import app
from tasks.recon import run_recon

logger = logging.getLogger(__name__)


@app.task(
    bind=True,
    name="tasks.scheduled.run_due_scans",
    soft_time_limit=120,
    time_limit=300,
)
def run_due_scans(self):
    """
    Runs every 5 minutes via Celery Beat.
    Finds scheduled engagements due to run and dispatches them as real engagements.
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.warning("DATABASE_URL not set, skipping scheduled scans check")
        return {"status": "skipped", "reason": "no DATABASE_URL"}

    from database.connection import connect

    conn = connect(db_url)
    cursor = conn.cursor()

    try:
        # Find all enabled schedules that are due to run
        cursor.execute(
            """
            SELECT id, org_id, target_url, authorized_scope, scan_type,
                   aggressiveness, agent_mode, created_by
            FROM scheduled_engagements
            WHERE enabled = TRUE
            AND next_run_at <= NOW()
            FOR UPDATE SKIP LOCKED
            """
        )
        due = cursor.fetchall()

        spawned = 0
        for row in due:
            (
                sched_id,
                org_id,
                target,
                scope,
                scan_type,
                aggr,
                agent_mode,
                created_by,
            ) = row

            try:
                _spawn_engagement(
                    conn=conn,
                    sched_id=sched_id,
                    org_id=org_id,
                    target=target,
                    scope=scope,
                    scan_type=scan_type,
                    aggressiveness=aggr,
                    agent_mode=agent_mode,
                    created_by=created_by,
                    db_url=db_url,
                )
                spawned += 1
            except Exception as e:
                logger.error("Failed to spawn scheduled engagement %s: %s", sched_id, e)
                # Continue with next schedule — don't fail the batch

        conn.commit()
        logger.info("Spawned %d scheduled engagement(s)", spawned)
        return {"status": "completed", "spawned": spawned}

    except Exception as e:
        conn.rollback()
        logger.error("run_due_scans failed: %s", e)
        return {"status": "failed", "error": str(e)}
    finally:
        cursor.close()
        conn.close()


def _spawn_engagement(
    conn,
    sched_id: str,
    org_id: str,
    target: str,
    scope: dict,
    scan_type: str,
    aggressiveness: str,
    agent_mode: bool,
    created_by: str,
    db_url: str,
) -> None:
    """
    Create a real engagement from a scheduled engagement record.
    All DB operations use the provided connection for transactional consistency.
    """
    engagement_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())

    # Create the engagement
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO engagements (
                id, org_id, target_url, authorization_proof,
                authorized_scope, status, created_by, scan_type,
                scan_aggressiveness, agent_mode, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, 'created', %s, %s, %s, %s, NOW()
            )
            """,
            (
                engagement_id,
                org_id,
                target,
                "scheduled",
                scope,
                created_by,
                scan_type,
                aggressiveness,
                agent_mode,
            ),
        )

        # Initialize loop budget
        cursor.execute(
            """
            INSERT INTO loop_budgets (id, engagement_id, max_cycles, max_depth,
                                       current_cycles, current_depth, created_at)
            VALUES (%s, %s, 5, 3, 0, 0, NOW())
            """,
            (str(uuid.uuid4()), engagement_id),
        )

        # Record initial state
        cursor.execute(
            """
            INSERT INTO engagement_states (id, engagement_id, from_state, to_state,
                                            reason, created_at)
            VALUES (%s, %s, NULL, 'created', 'Scheduled engagement auto-created', NOW())
            """,
            (str(uuid.uuid4()), engagement_id),
        )

        # Update scheduled engagement with next run and last engagement reference
        cursor.execute(
            """
            UPDATE scheduled_engagements
            SET last_run_at = NOW(),
                next_run_at = CASE
                    WHEN cron_expression = '0 2 * * *' THEN NOW() + INTERVAL '1 day'
                    WHEN cron_expression = '0 2 * * 1' THEN NOW() + INTERVAL '7 days'
                    WHEN cron_expression = '0 2 1 * *' THEN NOW() + INTERVAL '1 month'
                    ELSE NOW() + INTERVAL '7 days'
                END,
                last_engagement_id = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (engagement_id, sched_id),
        )

        cursor.close()

    except Exception:
        cursor.close()
        raise

    # Look up previous engagement for this schedule (for diff engine)
    prev_engagement_id = None
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT last_engagement_id FROM scheduled_engagements WHERE id = %s",
            (sched_id,),
        )
        row = cursor.fetchone()
        if row and row[0]:
            prev_engagement_id = str(row[0])
        cursor.close()
    except Exception:
        prev_engagement_id = None

    # Dispatch Celery task asynchronously
    if scan_type == "repo":
        from tasks.repo_scan import run_repo_scan

        run_repo_scan.delay(
            engagement_id=engagement_id,
            target=target,
            budget={"max_cycles": 5, "max_depth": 3},
            trace_id=trace_id,
        )
    else:
        run_recon.delay(
            engagement_id=engagement_id,
            target=target,
            budget={"max_cycles": 5, "max_depth": 3},
            trace_id=trace_id,
            agent_mode=agent_mode,
            prev_engagement_id=prev_engagement_id,
        )

    logger.info(
        "Spawned engagement %s from schedule %s (target=%s, type=%s)",
        engagement_id,
        sched_id,
        target,
        scan_type,
    )
