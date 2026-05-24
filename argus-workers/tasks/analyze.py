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
    Execute analysis phase for an engagement.

    Analysis is consumed by the agent loop as intelligence for decision-making,
    not dispatched as batch actions. The orchestrator's run_analysis() handles
    all analysis processing through the evaluate() → analyze_state() path.
    """
    from utils.logging_utils import ScanLogger
    slog = ScanLogger("analyze", engagement_id=engagement_id)
    slog.phase_header("ANALYZE PHASE")

    with task_context(self, engagement_id, "analyze",
                      job_extra={"budget": budget},
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

        # Advance to reporting — dispatch task FIRST, then transition
        # to avoid being stuck in "reporting" with no running task.
        try:
            app.send_task('tasks.report.generate_report',
                          args=[engagement_id, ctx.trace_id, budget])
        except Exception as e:
            logger.error("Failed to enqueue report for engagement=%s: %s", engagement_id, e, exc_info=True)
            ctx.state.safe_transition("failed", f"Failed to enqueue report: {e}")
            return result

        ctx.state.transition("reporting", "Analysis complete — report dispatched")

        return result
