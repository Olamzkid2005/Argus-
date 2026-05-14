"""
Celery tasks for analysis phase

Requirements: 20.1, 20.2, 20.3
"""
import logging

from celery_app import app
from tasks.base import task_context

logger = logging.getLogger(__name__)


@app.task(bind=True, name="tasks.analyze.run_analysis")
def run_analysis(self, engagement_id: str, budget: dict, trace_id: str = None):
    """
    Execute analysis phase for an engagement
    """
    from utils.logging_utils import ScanLogger
    slog = ScanLogger("analyze", engagement_id=engagement_id)
    slog.phase_header("ANALYZE PHASE")

    with task_context(self, engagement_id, "analyze",
                      job_extra={"budget": budget},
                      trace_id=trace_id, current_state="analyzing") as ctx:
        result = ctx.orchestrator.run_analysis(ctx.job)

        actions = result.get("actions", [])
        result.get("next_state", "reporting")
        if actions:
            slog.info(f"{len(actions)} action(s) generated — re-entering recon")
            # Extract targets from analysis actions so expand_recon receives real targets
            action_targets = []
            for action in actions:
                target = None
                if isinstance(action, dict):
                    target = action.get("target") or action.get("arguments", {}).get("target")
                if target and isinstance(target, str):
                    action_targets.append(target)
            if not action_targets:
                logger.warning("Analysis actions found but no valid targets extracted for engagement=%s", engagement_id)
            # Dispatch the downstream task BEFORE transitioning state
            try:
                expand_task = app.send_task('tasks.recon.expand_recon',
                              args=[engagement_id, action_targets, budget, ctx.trace_id])
                slog.dispatch("expand_recon", task_id=expand_task.id)
                ctx.state.transition("recon", "Additional targets discovered")
                logger.info("Dispatched expand_recon for engagement=%s with %d targets (task=%s)",
                           engagement_id, len(action_targets), expand_task.id)
            except Exception as e:
                logger.error("Failed to enqueue expand_recon for engagement=%s: %s", engagement_id, e, exc_info=True)
                ctx.state.transition("failed", f"Failed to dispatch expand_recon: {e}")
        else:
            slog.info("No actions — advancing to reporting")
            ctx.state.transition("reporting", "Analysis complete")
            try:
                app.send_task('tasks.report.generate_report',
                              args=[engagement_id, ctx.trace_id, budget])
            except Exception as e:
                logger.error("Failed to enqueue report for engagement=%s: %s", engagement_id, e, exc_info=True)

        return result
