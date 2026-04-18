"""
Celery tasks for reporting phase

Requirements: 20.1, 20.2, 20.3
"""
from celery_app import app
import os

from tracing import TracingManager, TraceContext


@app.task(bind=True, name="tasks.report.generate_report")
def generate_report(self, engagement_id: str, trace_id: str = None):
    """
    Generate final report for an engagement

    Args:
        engagement_id: Engagement ID
        trace_id: Optional trace_id for distributed tracing (generated if not provided)
    """
    from orchestrator import Orchestrator
    from distributed_lock import LockContext, DistributedLock
    from state_machine import EngagementStateMachine

    db_conn = os.getenv("DATABASE_URL")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    
    # Initialize tracing manager
    tracing_manager = TracingManager(db_conn)
    
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
                    engagement_id, db_conn, "reporting"
                )

                orchestrator = Orchestrator(engagement_id, trace_id=trace_id)
                result = orchestrator.run_reporting(job)

                state_machine.transition("complete", "Report generated")

                return result
        except Exception as e:
            state_machine = EngagementStateMachine(
                engagement_id, db_conn
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
    import psycopg2
    from psycopg2.extras import RealDictCursor

    db_conn = os.getenv("DATABASE_URL")
    
    # Initialize tracing manager
    tracing_manager = TracingManager(db_conn)
    
    # Create or use existing trace context
    if not trace_id:
        trace_id = tracing_manager.generate_trace_id()
    
    # Execute with trace context
    with tracing_manager.trace_execution(engagement_id, "findings_summary", trace_id):
        conn = psycopg2.connect(db_conn)
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
