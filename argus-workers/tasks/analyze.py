"""
Celery tasks for analysis phase

Requirements: 20.1, 20.2, 20.3
"""
from celery_app import app
import os

from tracing import TracingManager, TraceContext


@app.task(bind=True, name="tasks.analyze.run_analysis")
def run_analysis(self, engagement_id: str, budget: dict, trace_id: str = None):
    """
    Execute analysis phase for an engagement

    Args:
        engagement_id: Engagement ID
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
                    engagement_id, db_conn, "analyzing"
                )

                orchestrator = Orchestrator(engagement_id, trace_id=trace_id)
                result = orchestrator.run_analysis(job)

                actions = result.get("actions", [])
                if actions:
                    state_machine.transition("recon", "Additional targets discovered")
                else:
                    state_machine.transition("reporting", "Analysis complete")

                return result
        except Exception as e:
            state_machine = EngagementStateMachine(
                engagement_id, db_conn
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
    from intelligence_engine import IntelligenceEngine
    from snapshot_manager import SnapshotManager

    db_conn = os.getenv("DATABASE_URL")
    
    # Initialize tracing manager
    tracing_manager = TracingManager(db_conn)
    
    # Create or use existing trace context
    if not trace_id:
        trace_id = tracing_manager.generate_trace_id()
    
    # Execute with trace context
    with tracing_manager.trace_execution(engagement_id, "evaluate_findings", trace_id):
        snapshot_mgr = SnapshotManager(db_conn)

        snapshot = snapshot_mgr.create_snapshot(engagement_id)
        engine = IntelligenceEngine(db_conn)

        return engine.evaluate(snapshot)
