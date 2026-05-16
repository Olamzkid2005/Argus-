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
        if actions:
            slog.info(f"{len(actions)} action(s) generated — processing")
            _dispatched = 0
            # Route each action type to the correct downstream task
            for action in actions:
                action_type = action.get("type", "") if isinstance(action, dict) else ""
                if action_type == "deep_scan":
                    targets = action.get("targets", []) if isinstance(action, dict) else []
                    if targets:
                        try:
                            deep_task = app.send_task('tasks.scan.deep_scan',
                                          args=[engagement_id, targets, budget, ctx.trace_id])
                            slog.dispatch("deep_scan", task_id=deep_task.id)
                            _dispatched += 1
                            logger.info("Dispatched deep_scan for engagement=%s with %d targets (task=%s)",
                                       engagement_id, len(targets), deep_task.id)
                        except Exception as e:
                            logger.error("Failed to enqueue deep_scan for %s: %s", engagement_id, e, exc_info=True)
                elif action_type == "auth_focused_scan":
                    endpoints = action.get("endpoints", []) if isinstance(action, dict) else []
                    if endpoints:
                        try:
                            auth_task = app.send_task('tasks.scan.auth_focused_scan',
                                          args=[engagement_id, endpoints, budget, ctx.trace_id])
                            slog.dispatch("auth_focused_scan", task_id=auth_task.id)
                            _dispatched += 1
                            logger.info("Dispatched auth_focused_scan for engagement=%s (task=%s)",
                                       engagement_id, auth_task.id)
                        except Exception as e:
                            logger.error("Failed to enqueue auth_focused_scan for %s: %s", engagement_id, e, exc_info=True)
                else:
                    # Default: extract targets and expand recon
                    target = None
                    if isinstance(action, dict):
                        target = action.get("target") or action.get("arguments", {}).get("target")
                    if target and isinstance(target, str):
                        try:
                            expand_task = app.send_task('tasks.recon.expand_recon',
                                          args=[engagement_id, [target], budget, ctx.trace_id])
                            slog.dispatch("expand_recon", task_id=expand_task.id)
                            _dispatched += 1
                            logger.info("Dispatched expand_recon for engagement=%s with target %s (task=%s)",
                                       engagement_id, target, expand_task.id)
                        except Exception as e:
                            logger.error("Failed to enqueue expand_recon for %s: %s", engagement_id, e, exc_info=True)
                    else:
                        logger.warning("Action %s has no valid targets for engagement=%s", action_type, engagement_id)

            if _dispatched == 0:
                logger.info("All %d action(s) had empty/invalid targets for engagement=%s — advancing to reporting", len(actions), engagement_id)
                ctx.state.transition("reporting", "No actionable targets — advancing to report")
                try:
                    app.send_task('tasks.report.generate_report',
                                  args=[engagement_id, ctx.trace_id, budget])
                except Exception as e:
                    logger.error("Failed to enqueue report for engagement=%s: %s", engagement_id, e, exc_info=True)
                    ctx.state.transition("failed", f"Failed to enqueue report: {e}")
            else:
                # Transition to "recon" (not "scanning") so the loop budget
                # counter increments in state_machine.py (analyzing→recon).
                # The dispatched expand_recon/deep_scan tasks will advance
                # state to scanning automatically.
                ctx.state.transition("recon", f"{_dispatched} action(s) dispatched — looping through recon")
        else:
            slog.info("No actions — advancing to reporting")
            ctx.state.transition("reporting", "Analysis complete")
            try:
                app.send_task('tasks.report.generate_report',
                              args=[engagement_id, ctx.trace_id, budget])
            except Exception as e:
                logger.error("Failed to enqueue report for engagement=%s: %s", engagement_id, e, exc_info=True)
                ctx.state.transition("failed", f"Failed to enqueue report: {e}")

        return result
