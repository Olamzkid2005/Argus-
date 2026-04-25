"""
Celery tasks for reconnaissance phase

Requirements: 4.2, 4.4, 20.1, 20.2, 20.3
"""
import os
from celery_app import app
from database.connection import connect

from tasks.loader import load_module
from utils.validation import validate_uuid

_orchestrator = load_module("orchestrator")
Orchestrator = _orchestrator.Orchestrator

_tracing = load_module("tracing")
TracingManager = _tracing.TracingManager

_distributed_lock = load_module("distributed_lock")
LockContext = _distributed_lock.LockContext
DistributedLock = _distributed_lock.DistributedLock

_state_machine = load_module("state_machine")
EngagementStateMachine = _state_machine.EngagementStateMachine


@app.task(bind=True, name="tasks.recon.run_recon")
def run_recon(self, engagement_id: str, target: str, budget: dict, trace_id: str = None):
    """
    Execute reconnaissance phase for an engagement

    Args:
        engagement_id: Engagement ID
        target: Target URL
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
    with tracing_manager.trace_execution(engagement_id, "recon", trace_id):
        job = {
            "type": "recon",
            "engagement_id": engagement_id,
            "target": target,
            "budget": budget,
            "trace_id": trace_id,
        }

        lock = DistributedLock(redis_url)

        try:
            with LockContext(lock, engagement_id):
                state_machine = EngagementStateMachine(
                    engagement_id, db_connection_string=db_conn_string, current_state="created"
                )
                state_machine.transition("recon", "Starting reconnaissance")

                orchestrator = Orchestrator(engagement_id, trace_id=trace_id)
                result = orchestrator.run_recon(job)

                state_machine.transition("awaiting_approval", "Recon complete")

                return result
        except Exception as e:
            # Query actual current state from DB before transitioning to failed
            current_state = _get_engagement_state(engagement_id, db_conn_string)
            state_machine = EngagementStateMachine(
                engagement_id, db_connection_string=db_conn_string, current_state=current_state
            )
            state_machine.transition("failed", f"Recon failed: {str(e)}")
            raise


@app.task(bind=True, name="tasks.recon.expand_recon")
def expand_recon(self, engagement_id: str, targets: list, budget: dict, trace_id: str = None):
    """
    Expand reconnaissance with additional targets

    Args:
        engagement_id: Engagement ID
        targets: List of additional target URLs
        budget: Budget configuration
        trace_id: Optional trace_id for distributed tracing
    """
    db_conn_string = os.getenv("DATABASE_URL")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

    # Initialize tracing manager
    tracing_manager = TracingManager(db_conn_string)

    # Create or use existing trace context
    if not trace_id:
        trace_id = tracing_manager.generate_trace_id()

    # Execute with trace context
    with tracing_manager.trace_execution(engagement_id, "recon_expand", trace_id):
        job = {
            "type": "recon_expand",
            "engagement_id": engagement_id,
            "targets": targets,
            "budget": budget,
            "trace_id": trace_id,
        }

        lock = DistributedLock(redis_url)

        with LockContext(lock, engagement_id):
            orchestrator = Orchestrator(engagement_id, trace_id=trace_id)
            return orchestrator.run_recon(job)


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
