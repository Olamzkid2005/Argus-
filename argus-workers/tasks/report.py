"""
Celery tasks for reporting phase

Requirements: 20.1, 20.2, 20.3
"""
from celery_app import app
import os
import sys
import importlib.util

_workers_dir = "/Users/mac/Documents/Argus-/argus-workers"

# Robust module loader — avoids sys.path issues in Celery fork pool workers
def _load_module(module_name: str, rel_path: str = None):
    rel_path = rel_path or f"{module_name}.py"
    file_path = os.path.join(_workers_dir, rel_path)
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_orchestrator = _load_module("orchestrator")
Orchestrator = _orchestrator.Orchestrator

_tracing = _load_module("tracing")
TracingManager = _tracing.TracingManager
TraceContext = _tracing.TraceContext

import psycopg2
from psycopg2.extras import RealDictCursor

_distributed_lock = _load_module("distributed_lock")
LockContext = _distributed_lock.LockContext
DistributedLock = _distributed_lock.DistributedLock

_state_machine = _load_module("state_machine")
EngagementStateMachine = _state_machine.EngagementStateMachine


@app.task(bind=True, name="tasks.report.generate_report")
def generate_report(self, engagement_id: str, trace_id: str = None):
    """
    Generate final report for an engagement

    Args:
        engagement_id: Engagement ID
        trace_id: Optional trace_id for distributed tracing (generated if not provided)
    """
    db_conn_string = os.getenv("DATABASE_URL")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

    # Initialize tracing manager
    tracing_manager = TracingManager(db_conn_string)

    # Create or use existing trace context
    if not trace_id:
        trace_id = tracing_manager.generate_trace_id()

    # Execute with trace context
    with tracing_manager.trace_execution(engagement_id, "report", trace_id):
        job = {
            "type": "report",
            "engagement_id": engagement_id,
            "trace_id": trace_id,
        }

        lock = DistributedLock(redis_url)

        try:
            with LockContext(lock, engagement_id):
                state_machine = EngagementStateMachine(
                    engagement_id, db_connection_string=db_conn_string, current_state="reporting"
                )

                orchestrator = Orchestrator(engagement_id, trace_id=trace_id)
                result = orchestrator.run_reporting(job)

                state_machine.transition("complete", "Report generated")

                return result
        except Exception as e:
            # Query actual current state from DB before transitioning to failed
            current_state = _get_engagement_state(engagement_id, db_conn_string)
            state_machine = EngagementStateMachine(
                engagement_id, db_connection_string=db_conn_string, current_state=current_state
            )
            state_machine.transition("failed", f"Reporting failed: {str(e)}")
            raise


@app.task(bind=True, name="tasks.report.get_findings_summary")
def get_findings_summary(self, engagement_id: str, trace_id: str = None):
    """
    Get findings summary for an engagement

    Args:
        engagement_id: Engagement ID
        trace_id: Optional trace_id for distributed tracing
    """
    db_conn_string = os.getenv("DATABASE_URL")

    # Initialize tracing manager
    tracing_manager = TracingManager(db_conn_string)

    # Create or use existing trace context
    if not trace_id:
        trace_id = tracing_manager.generate_trace_id()

    # Execute with trace context
    with tracing_manager.trace_execution(engagement_id, "findings_summary", trace_id):
        conn = psycopg2.connect(db_conn_string)
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cursor.execute(
                """
                SELECT
                    severity,
                    COUNT(*) as count,
                    AVG(confidence) as avg_confidence
                FROM findings
                WHERE engagement_id = %s
                GROUP BY severity
                ORDER BY
                    CASE severity
                        WHEN 'CRITICAL' THEN 1
                        WHEN 'HIGH' THEN 2
                        WHEN 'MEDIUM' THEN 3
                        WHEN 'LOW' THEN 4
                        WHEN 'INFO' THEN 5
                    END
                """,
                (engagement_id,)
            )

            return [dict(row) for row in cursor.fetchall()]
        finally:
            cursor.close()
            conn.close()


def _get_engagement_state(engagement_id: str, db_conn_string: str) -> str:
    """
    Query the current engagement state from the database.

    Args:
        engagement_id: Engagement ID
        db_conn_string: Database connection string

    Returns:
        Current engagement status string
    """
    try:
        conn = psycopg2.connect(db_conn_string)
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM engagements WHERE id = %s", (engagement_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return row[0] if row else "created"
    except Exception:
        return "created"
