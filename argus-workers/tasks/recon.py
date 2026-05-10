"""
Celery tasks for reconnaissance phase

Requirements: 4.2, 4.4, 20.1, 20.2, 20.3
"""
import logging

from celery_app import app
from tasks.base import task_context

logger = logging.getLogger(__name__)


@app.task(
    bind=True,
    name="tasks.recon.run_recon",
    soft_time_limit=2400,   # 40 minutes for long-running recon tools
    time_limit=3600,        # 60 minutes hard limit
)
def run_recon(self, engagement_id: str, target: str, budget: dict, trace_id: str = None,
              agent_mode: bool = True, prev_engagement_id: str | None = None):
    """
    Execute reconnaissance phase for an engagement

    Args:
        engagement_id: Engagement UUID
        target: Target URL
        budget: Budget config dict
        trace_id: Optional trace ID
        agent_mode: Enable LLM agent mode
        prev_engagement_id: Previous engagement ID for diff engine (scheduled scans)
    """
    # Forward prev_engagement_id through the chain via budget
    if prev_engagement_id:
        budget["prev_engagement_id"] = prev_engagement_id

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

        # Save updated recon context to Redis so scan can read it
        if result.get("recon_context"):
            try:
                from tasks.utils import save_recon_context
                ctx_data = result["recon_context"]
                if isinstance(ctx_data, dict):
                    from models.recon_context import ReconContext
                    ctx_data = ReconContext.from_dict(ctx_data)
                save_recon_context(engagement_id, ctx_data)
                logger.info("Saved expanded recon context for %s", engagement_id)
            except Exception as e:
                logger.warning("Failed to save expanded recon context: %s", e)

        ctx.state.transition("scanning", "Expanded recon complete — auto-advancing to scan")
        app.send_task('tasks.scan.run_scan', args=[engagement_id, valid_targets, budget, ctx.trace_id])
        return result

