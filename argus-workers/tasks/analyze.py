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
    with task_context(self, engagement_id, "analyze",
                      job_extra={"budget": budget},
                      trace_id=trace_id, current_state="analyzing") as ctx:
        result = ctx.orchestrator.run_analysis(ctx.job)

        actions = result.get("actions", [])
        result.get("next_state", "reporting")
        if actions:
            ctx.state.transition("recon", "Additional targets discovered")
            try:
                app.send_task('tasks.recon.expand_recon',
                              args=[engagement_id, [], budget, ctx.trace_id])
            except Exception as e:
                logger.error("Failed to enqueue expand_recon for engagement=%s: %s", engagement_id, e, exc_info=True)
        else:
            ctx.state.transition("reporting", "Analysis complete")
            try:
                app.send_task('tasks.report.generate_report',
                              args=[engagement_id, ctx.trace_id, budget])
            except Exception as e:
                logger.error("Failed to enqueue report for engagement=%s: %s", engagement_id, e, exc_info=True)

        return result
