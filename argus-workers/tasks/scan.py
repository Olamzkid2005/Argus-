"""
Celery tasks for scanning phase

Requirements: 4.3, 4.4, 20.1, 20.2, 20.3
"""
from celery_app import app
import os

from tracing import TracingManager, TraceContext


@app.task(bind=True, name="tasks.scan.run_scan")
def run_scan(self, engagement_id: str, targets: list, budget: dict, trace_id: str = None):
    """
    Execute scanning phase for an engagement

    Args:
        engagement_id: Engagement ID
        targets: List of target URLs to scan
        budget: Budget configuration
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
                state_machine = EngagementStateMachine(
                    engagement_id, db_conn, "awaiting_approval"
                )
                state_machine.transition("scanning", "Starting scan")

                orchestrator = Orchestrator(engagement_id, trace_id=trace_id)
                result = orchestrator.run_scan(job)

                state_machine.transition("analyzing", "Scan complete")

                return result
        except Exception as e:
            state_machine = EngagementStateMachine(
                engagement_id, db_conn
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
