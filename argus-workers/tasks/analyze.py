"""
Celery tasks for analysis phase

Requirements: 20.1, 20.2, 20.3
"""
import os
from celery_app import app
from database.connection import connect

from utils.validation import validate_uuid
from orchestrator import Orchestrator
from tracing import TracingManager
from distributed_lock import LockContext, DistributedLock
from state_machine import EngagementStateMachine
from intelligence_engine import IntelligenceEngine
from snapshot_manager import SnapshotManager


@app.task(bind=True, name="tasks.analyze.run_analysis")
def run_analysis(self, engagement_id: str, budget: dict, trace_id: str = None):
    """
    Execute analysis phase for an engagement

    Args:
        engagement_id: Engagement ID
        budget: Budget configuration
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
    with tracing_manager.trace_execution(engagement_id, "analyze", trace_id):
        job = {
            "type": "analyze",
            "engagement_id": engagement_id,
            "budget": budget,
            "trace_id": trace_id,
        }

        lock = DistributedLock(redis_url)

        try:
            with LockContext(lock, engagement_id):
                state_machine = EngagementStateMachine(
                    engagement_id, db_connection_string=db_conn_string, current_state="analyzing"
                )

                orchestrator = Orchestrator(engagement_id, trace_id=trace_id)
                result = orchestrator.run_analysis(job)

                actions = result.get("actions", [])
                next_state = result.get("next_state", "reporting")
                if actions:
                    state_machine.transition("recon", "Additional targets discovered")
                    # Push expand recon job for next scan cycle
                    app.send_task(
                        'tasks.recon.expand_recon',
                        args=[
                            engagement_id,
                            [],  # targets will be populated from analysis scope
                            budget,
                            trace_id,
                        ],
                    )
                else:
                    state_machine.transition("reporting", "Analysis complete")
                    # Push report generation job
                    app.send_task(
                        'tasks.report.generate_report',
                        args=[engagement_id, trace_id],
                    )

                return result
        except Exception as e:
            # Query actual current state from DB before transitioning to failed
            current_state = _get_engagement_state(engagement_id, db_conn_string)
            if current_state != "failed":
                state_machine = EngagementStateMachine(
                    engagement_id, db_connection_string=db_conn_string, current_state=current_state
                )
                state_machine.transition("failed", f"Analysis failed: {str(e)}")
            raise


@app.task(bind=True, name="tasks.analyze.evaluate_findings")
def evaluate_findings(self, engagement_id: str, trace_id: str = None):
    """
    Evaluate findings and generate intelligence actions

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
    with tracing_manager.trace_execution(engagement_id, "evaluate_findings", trace_id):
        snapshot_mgr = SnapshotManager(db_conn_string)

        snapshot = snapshot_mgr.create_snapshot(engagement_id)
        engine = IntelligenceEngine(db_conn_string)

        return engine.evaluate(snapshot)


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
        # Validate UUID before DB query to prevent InvalidTextRepresentation errors
        valid_id = validate_uuid(engagement_id, "engagement_id")
        conn = connect(db_conn_string)
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM engagements WHERE id = %s", (valid_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return row[0] if row else "created"
    except Exception:
        return "created"
