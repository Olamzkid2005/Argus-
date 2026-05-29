"""
Celery tasks for analysis phase

Requirements: 20.1, 20.2, 20.3
"""
import logging

from celery_app import app
from tasks.base import task_context

logger = logging.getLogger(__name__)


@app.task(bind=True, name="tasks.analyze.run_analysis", soft_time_limit=1800, time_limit=2400)
def run_analysis(self, engagement_id: str, budget: dict, trace_id: str = None,
                 bug_bounty_mode: bool | None = None):
    """
    Execute analysis phase for an engagement.

    Analysis is consumed by the agent loop as intelligence for decision-making,
    not dispatched as batch actions. The orchestrator's run_analysis() handles
    all analysis processing through the evaluate() → analyze_state() path.

    Args:
        engagement_id: Engagement UUID
        budget: Budget config dict
        trace_id: Optional trace ID
        bug_bounty_mode: Forwarded from scan phase for report generation
    """
    from utils.logging_utils import ScanLogger
    slog = ScanLogger("analyze", engagement_id=engagement_id)
    slog.phase_header("ANALYZE PHASE")

    job_extra = {"budget": budget}
    if bug_bounty_mode is not None:
        job_extra["bug_bounty_mode"] = bug_bounty_mode

    with task_context(self, engagement_id, "analyze",
                      job_extra=job_extra,
                      trace_id=trace_id, current_state="analyzing") as ctx:
        result = ctx.orchestrator.run_analysis(ctx.job)

        analysis = result.get("analysis", {})
        slog.info(
            "Analysis complete — risk=%s, "
            "coverage_gaps=%d, high_value_targets=%d",
            analysis.get("risk_level", "unknown"),
            len(analysis.get("coverage_gaps", [])),
            len(analysis.get("high_value_targets", [])),
        )

        # Advance to reporting — transition FIRST so the report task
        # always finds the engagement in "reporting" state. If transition
        # fails, no downstream task is dispatched and the engagement
        # stays in "analyzing" (handled by the ctx.state exception below).
        # If transition succeeds but dispatch fails, we transition to
        # "failed" cleanly (analyzing→reporting→failed is valid).
        try:
            ctx.state.transition("reporting", "Analysis complete — advancing to report")
        except Exception as e:
            logger.error("Failed to transition to reporting for engagement=%s: %s", engagement_id, e, exc_info=True)
            ctx.state.safe_transition("failed", f"State transition failed: {e}")
            result["status"] = "failed"
            result["reason"] = "state_transition_failed"
            return result
        try:
            app.send_task('tasks.report.generate_report',
                          args=[engagement_id, ctx.trace_id, budget])
        except Exception as e:
            logger.error("Failed to enqueue report for engagement=%s: %s", engagement_id, e, exc_info=True)
            ctx.state.safe_transition("failed", f"Failed to enqueue report: {e}")
            result["status"] = "failed"
            result["reason"] = "report_dispatch_failed"
            return result

        return result
