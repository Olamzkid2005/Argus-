"""
Celery tasks for analysis phase

Requirements: 20.1, 20.2, 20.3
"""
from celery_app import app
from tasks.base import task_context


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
            app.send_task('tasks.recon.expand_recon',
                          args=[engagement_id, [], budget, ctx.trace_id])
        else:
            ctx.state.transition("reporting", "Analysis complete")
            app.send_task('tasks.report.generate_report',
                          args=[engagement_id, ctx.trace_id])

        return result
