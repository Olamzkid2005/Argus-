"""
Celery tasks for reconnaissance phase

Requirements: 4.2, 4.4, 20.1, 20.2, 20.3
"""
import logging
import os
from celery_app import app
from database.connection import connect, db_cursor

logger = logging.getLogger(__name__)

from utils.validation import validate_uuid
from orchestrator import Orchestrator
from tracing import TracingManager
from distributed_lock import LockContext, DistributedLock
from state_machine import EngagementStateMachine


@app.task(bind=True, name="tasks.recon.run_recon")
def run_recon(self, engagement_id: str, target: str, budget: dict, trace_id: str = None, agent_mode: bool = True):
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
            "agent_mode": agent_mode,
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

                # Fire-and-forget asset discovery (non-blocking, independently retryable)
                try:
                    app.send_task(
                        'tasks.asset_discovery.run_asset_discovery',
                        args=[engagement_id, target, trace_id],
                        countdown=5,
                    )
                except Exception as e:
                    logger.warning("Failed to enqueue asset discovery for %s: %s", engagement_id, e)

                # Don't transition to "scanning" here — scan.py handles that transition
                # and verifies the state is valid before proceeding
                # Auto-push scan job (skip awaiting_approval phase)
                app.send_task(
                    'tasks.scan.run_scan',
                    args=[engagement_id, [target], budget, trace_id, agent_mode],
                )

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
        # Filter valid targets
        valid_targets = [t for t in targets if t and isinstance(t, str)]
        if not valid_targets:
            logger.warning(f"expand_recon called with empty/invalid targets for engagement {engagement_id}, skipping")
            return {"phase": "recon_expand", "status": "skipped", "reason": "no_valid_targets"}

        job = {
            "type": "recon_expand",
            "engagement_id": engagement_id,
            "target": valid_targets[0],
            "targets": valid_targets,
            "budget": budget,
            "trace_id": trace_id,
        }

        lock = DistributedLock(redis_url)

        try:
            with LockContext(lock, engagement_id):
                state_machine = EngagementStateMachine(
                    engagement_id, db_connection_string=db_conn_string, current_state="recon"
                )

                orchestrator = Orchestrator(engagement_id, trace_id=trace_id)
                result = orchestrator.run_recon(job)

                state_machine.transition("scanning", "Expanded recon complete — auto-advancing to scan")
                # Auto-push scan job (skip awaiting_approval phase)
                app.send_task(
                    'tasks.scan.run_scan',
                    args=[engagement_id, valid_targets, budget, trace_id],
                )

                return result
        except Exception as e:
            # Query actual current state from DB before transitioning to failed
            current_state = _get_engagement_state(engagement_id, db_conn_string)
            # Skip if already in failed state
            if current_state != "failed":
                state_machine = EngagementStateMachine(
                    engagement_id, db_connection_string=db_conn_string, current_state=current_state
                )
                state_machine.transition("failed", f"Expand recon failed: {str(e)}")
            raise


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
        from database.connection import db_cursor
        with db_cursor() as cursor:
            cursor.execute("SELECT status FROM engagements WHERE id = %s", (valid_id,))
            row = cursor.fetchone()
        return row[0] if row else "created"
    except Exception:
        return "created"
