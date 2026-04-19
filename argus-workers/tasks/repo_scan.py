"""
Celery tasks for repository scanning phase

Scans GitHub/GitLab repositories for code vulnerabilities using Semgrep
with custom rules based on vibe-security-ultra framework.

Requirements: 4.2, 4.4, 20.1, 20.2, 20.3
"""
from celery_app import app
import os
import psycopg2

from tracing import TracingManager, TraceContext


@app.task(bind=True, name="tasks.repo_scan.run_repo_scan")
def run_repo_scan(self, engagement_id: str, repo_url: str, budget: dict, trace_id: str = None):
    """
    Execute repository scanning phase for an engagement

    Args:
        engagement_id: Engagement ID
        repo_url: GitHub/GitLab repository URL
        budget: Budget configuration
        trace_id: Optional trace_id for distributed tracing (generated if not provided)
    """
    from orchestrator import Orchestrator
    from distributed_lock import LockContext, DistributedLock
    from snapshot_manager import SnapshotManager
    from state_machine import EngagementStateMachine

    db_conn_string = os.getenv("DATABASE_URL")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

    # Initialize tracing manager
    tracing_manager = TracingManager(db_conn_string)

    # Create or use existing trace context
    if not trace_id:
        trace_id = tracing_manager.generate_trace_id()

    # Execute with trace context
    with tracing_manager.trace_execution(engagement_id, "repo_scan", trace_id):
        job = {
            "type": "repo_scan",
            "engagement_id": engagement_id,
            "repo_url": repo_url,
            "budget": budget,
            "trace_id": trace_id,
        }

        lock = DistributedLock(redis_url)

        try:
            with LockContext(lock, engagement_id):
                state_machine = EngagementStateMachine(
                    engagement_id, db_connection_string=db_conn_string, current_state="created"
                )
                state_machine.transition("recon", "Starting repository scan")

                orchestrator = Orchestrator(engagement_id, trace_id=trace_id)
                result = orchestrator.run_repo_scan(job)

                state_machine.transition("awaiting_approval", "Repository scan complete")

                return result
        except Exception as e:
            # Query actual current state from DB before transitioning to failed
            current_state = _get_engagement_state(engagement_id, db_conn_string)
            state_machine = EngagementStateMachine(
                engagement_id, db_connection_string=db_conn_string, current_state=current_state
            )
            state_machine.transition("failed", f"Repository scan failed: {str(e)}")
            raise


@app.task(bind=True, name="tasks.repo_scan.expand_repo_scan")
def expand_repo_scan(self, engagement_id: str, repo_url: str, additional_rules_path: str, budget: dict, trace_id: str = None):
    """
    Expand repository scan with additional custom rules

    Args:
        engagement_id: Engagement ID
        repo_url: Repository URL
        additional_rules_path: Path to additional Semgrep rules
        budget: Budget configuration
        trace_id: Optional trace_id for distributed tracing
    """
    from orchestrator import Orchestrator
    from distributed_lock import LockContext, DistributedLock

    db_conn_string = os.getenv("DATABASE_URL")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

    # Initialize tracing manager
    tracing_manager = TracingManager(db_conn_string)

    # Create or use existing trace context
    if not trace_id:
        trace_id = tracing_manager.generate_trace_id()

    # Execute with trace context
    with tracing_manager.trace_execution(engagement_id, "repo_scan_expand", trace_id):
        job = {
            "type": "repo_scan_expand",
            "engagement_id": engagement_id,
            "repo_url": repo_url,
            "additional_rules_path": additional_rules_path,
            "budget": budget,
            "trace_id": trace_id,
        }

        lock = DistributedLock(redis_url)

        with LockContext(lock, engagement_id):
            orchestrator = Orchestrator(engagement_id, trace_id=trace_id)
            return orchestrator.run_repo_scan(job)


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