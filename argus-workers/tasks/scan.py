"""
Celery tasks for scanning phase

Requirements: 4.3, 4.4, 20.1, 20.2, 20.3
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


@app.task(bind=True, name="tasks.scan.run_scan", soft_time_limit=600, time_limit=1200)
def run_scan(self, engagement_id: str, targets: list, budget: dict, trace_id: str = None):
    """
    Execute scanning phase for an engagement

    Args:
        engagement_id: Engagement ID
        targets: List of target URLs to scan
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
    with tracing_manager.trace_execution(engagement_id, "scan", trace_id):
        job = {
            "type": "scan",
            "engagement_id": engagement_id,
            "targets": targets,
            "budget": budget,
            "trace_id": trace_id,
        }

        lock = DistributedLock(redis_url)

        try:
            with LockContext(lock, engagement_id):
                # Read actual state from DB instead of hardcoding
                current_state = _get_engagement_state(engagement_id, db_conn_string)
                state_machine = EngagementStateMachine(
                    engagement_id, db_connection_string=db_conn_string, current_state=current_state
                )
                state_machine.transition("scanning", "Starting scan")

                orchestrator = Orchestrator(engagement_id, trace_id=trace_id)
                result = orchestrator.run_scan(job)

                state_machine.transition("analyzing", "Scan complete")

                # Queue analysis phase immediately after successful scan.
                # The worker already routes tasks.analyze.* to the "analyze" queue.
                analyze_task = app.send_task(
                    "tasks.analyze.run_analysis",
                    args=[engagement_id, budget, trace_id],
                )
                result["analysis_task_id"] = analyze_task.id

                return result
        except Exception as e:
            # Query actual current state from DB before transitioning to failed
            current_state = _get_engagement_state(engagement_id, db_conn_string)
            state_machine = EngagementStateMachine(
                engagement_id, db_connection_string=db_conn_string, current_state=current_state
            )
            state_machine.transition("failed", f"Scan failed: {str(e)}")
            raise


@app.task(bind=True, name="tasks.scan.deep_scan")
def deep_scan(self, engagement_id: str, targets: list, budget: dict, trace_id: str = None):
    """
    Execute deep scanning on specific targets

    Args:
        engagement_id: Engagement ID
        targets: List of priority target URLs
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
    with tracing_manager.trace_execution(engagement_id, "deep_scan", trace_id):
        job = {
            "type": "deep_scan",
            "engagement_id": engagement_id,
            "targets": targets,
            "budget": budget,
            "trace_id": trace_id,
        }

        lock = DistributedLock(redis_url)

        with LockContext(lock, engagement_id):
            orchestrator = Orchestrator(engagement_id, trace_id=trace_id)
            return orchestrator.run_scan(job)


@app.task(bind=True, name="tasks.scan.auth_focused_scan")
def auth_focused_scan(self, engagement_id: str, endpoints: list, budget: dict, trace_id: str = None):
    """
    Execute authentication-focused scanning

    Args:
        engagement_id: Engagement ID
        endpoints: List of authentication endpoints
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
    with tracing_manager.trace_execution(engagement_id, "auth_focused_scan", trace_id):
        job = {
            "type": "auth_focused_scan",
            "engagement_id": engagement_id,
            "endpoints": endpoints,
            "budget": budget,
            "trace_id": trace_id,
        }

        lock = DistributedLock(redis_url)

        with LockContext(lock, engagement_id):
            orchestrator = Orchestrator(engagement_id, trace_id=trace_id)
            return orchestrator.run_scan(job)


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
