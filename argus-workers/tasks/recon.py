"""
Celery tasks for reconnaissance phase

Requirements: 4.2, 4.4, 20.1, 20.2, 20.3
"""
import logging
from celery_app import app
from tasks.base import task_context

logger = logging.getLogger(__name__)


@app.task(bind=True, name="tasks.recon.run_recon")
def run_recon(self, engagement_id: str, target: str, budget: dict, trace_id: str = None, agent_mode: bool = True):
    """
    Execute reconnaissance phase for an engagement
    """
    with task_context(self, engagement_id, "recon",
                      job_extra={"target": target, "budget": budget, "agent_mode": agent_mode},
                      trace_id=trace_id, current_state="created") as ctx:
        ctx.state.transition("recon", "Starting reconnaissance")
        result = ctx.orchestrator.run_recon(ctx.job)

        try:
            app.send_task('tasks.asset_discovery.run_asset_discovery',
                          args=[engagement_id, target, ctx.trace_id], countdown=5)
        except Exception as e:
            logger.warning("Failed to enqueue asset discovery for %s: %s", engagement_id, e)

        app.send_task('tasks.scan.run_scan',
                      args=[engagement_id, [target], budget, ctx.trace_id, agent_mode])

        return result


@app.task(bind=True, name="tasks.recon.expand_recon")
def expand_recon(self, engagement_id: str, targets: list, budget: dict, trace_id: str = None):
    """
    Expand reconnaissance with additional targets
    """
    valid_targets = [t for t in targets if t and isinstance(t, str)]
    if not valid_targets:
        logger.warning(f"expand_recon called with empty/invalid targets for engagement {engagement_id}, skipping")
        return {"phase": "recon_expand", "status": "skipped", "reason": "no_valid_targets"}

    with task_context(self, engagement_id, "recon_expand",
                      job_extra={"target": valid_targets[0], "targets": valid_targets, "budget": budget},
                      trace_id=trace_id, current_state="recon") as ctx:
        result = ctx.orchestrator.run_recon(ctx.job)
        ctx.state.transition("scanning", "Expanded recon complete — auto-advancing to scan")
        app.send_task('tasks.scan.run_scan', args=[engagement_id, valid_targets, budget, ctx.trace_id])
        return result

