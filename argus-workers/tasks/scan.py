"""
Celery tasks for scanning phase

Requirements: 4.3, 4.4, 20.1, 20.2, 20.3
"""
from celery_app import app
from tasks.base import task_context


@app.task(bind=True, name="tasks.scan.run_scan", soft_time_limit=600, time_limit=1200)
def run_scan(self, engagement_id: str, targets: list, budget: dict, trace_id: str = None, agent_mode: bool = True):
    """
    Execute scanning phase for an engagement
    """
    # Load recon context from Redis for agent mode dispatch
    redis_url = None  # resolved inside task_context
    import os

    from tasks.utils import load_recon_context
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    recon_context = load_recon_context(engagement_id, redis_url)

    with task_context(self, engagement_id, "scan",
                      job_extra={"targets": targets, "budget": budget, "agent_mode": agent_mode,
                                 "recon_context": recon_context},
                      trace_id=trace_id) as ctx:
        ctx.state.transition("scanning", "Starting scan")
        result = ctx.orchestrator.run_scan(ctx.job)

        ctx.state.transition("analyzing", "Scan complete")

        analyze_task = app.send_task(
            "tasks.analyze.run_analysis",
            args=[engagement_id, budget, ctx.trace_id],
        )
        result["analysis_task_id"] = analyze_task.id

        return result


@app.task(bind=True, name="tasks.scan.deep_scan")
def deep_scan(self, engagement_id: str, targets: list, budget: dict, trace_id: str = None):
    """
    Execute deep scanning on specific targets
    """
    with task_context(self, engagement_id, "deep_scan",
                      job_extra={"targets": targets, "budget": budget},
                      trace_id=trace_id) as ctx:
        return ctx.orchestrator.run_scan(ctx.job)


@app.task(bind=True, name="tasks.scan.auth_focused_scan")
def auth_focused_scan(self, engagement_id: str, endpoints: list, budget: dict, trace_id: str = None):
    """
    Execute authentication-focused scanning
    """
    with task_context(self, engagement_id, "auth_focused_scan",
                      job_extra={"endpoints": endpoints, "budget": budget},
                      trace_id=trace_id) as ctx:
        return ctx.orchestrator.run_scan(ctx.job)

