"""
Celery tasks for reconnaissance phase

Requirements: 4.2, 4.4, 20.1, 20.2, 20.3
"""
from celery_app import app
import os

from tracing import TracingManager, TraceContext


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
    from orchestrator import Orchestrator
    from distributed_lock import LockContext, DistributedLock
    from snapshot_manager import SnapshotManager
    from state_machine import EngagementStateMachine

    db_conn = os.getenv("DATABASE_URL")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    
    # Initialize tracing manager
    tracing_manager = TracingManager(db_conn)
    
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
                    engagement_id, db_conn, "created"
                )
                state_machine.transition("recon", "Starting reconnaissance")

                orchestrator = Orchestrator(engagement_id, trace_id=trace_id)
                result = orchestrator.run_recon(job)

                state_machine.transition("awaiting_approval", "Recon complete")

                return result
        except Exception as e:
            state_machine = EngagementStateMachine(
                engagement_id, db_conn
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
    from orchestrator import Orchestrator
    from distributed_lock import LockContext, DistributedLock

    db_conn = os.getenv("DATABASE_URL")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    
    # Initialize tracing manager
    tracing_manager = TracingManager(db_conn)
    
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
