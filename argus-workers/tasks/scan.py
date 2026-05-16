"""
Celery tasks for scanning phase

Requirements: 4.3, 4.4, 20.1, 20.2, 20.3
"""
import logging
import os

from celery_app import app
from tasks.base import task_context

logger = logging.getLogger(__name__)


@app.task(bind=True, name="tasks.scan.run_scan", soft_time_limit=2400, time_limit=3600)
def run_scan(
    self,
    engagement_id: str,
    targets: list,
    budget: dict,
    trace_id: str = None,
    agent_mode: bool = True,
    scan_mode: str | None = None,
    aggressiveness: str | None = None,
    bug_bounty_mode: bool | None = None,
):
    """
    Execute scanning phase for an engagement
    """
    from utils.logging_utils import ScanLogger
    slog = ScanLogger("scan", engagement_id=engagement_id)

    # Load recon context from Redis for agent mode dispatch
    from tasks.utils import load_recon_context
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    try:
        recon_context = load_recon_context(engagement_id, redis_url)
        recon_info = f"{len(recon_context.live_endpoints) if hasattr(recon_context, 'live_endpoints') else 0} endpoints" if recon_context else "none"
        slog.info(f"Recon context loaded: {recon_info}")
    except Exception as e:
        logger.error("Failed to load recon context for engagement=%s: %s", engagement_id, e, exc_info=True)
        recon_context = None
        # Notify UI
        try:
            from streaming import emit_thinking
            emit_thinking(engagement_id, "Recon context unavailable — running deterministic scan")
        except Exception:
            pass

    mode = "agent" if agent_mode else "deterministic"
    slog.phase_header("SCAN PHASE", targets=f"{len(targets)} target(s)", mode=mode)

    job_extra = {
        "targets": targets,
        "budget": budget,
        "agent_mode": agent_mode,
        "recon_context": recon_context,
    }
    if scan_mode is not None:
        job_extra["scan_mode"] = scan_mode
    if aggressiveness is not None:
        job_extra["aggressiveness"] = aggressiveness
    if bug_bounty_mode is not None:
        job_extra["bug_bounty_mode"] = bug_bounty_mode

    with task_context(self, engagement_id, "scan",
                      job_extra=job_extra,
                      trace_id=trace_id) as ctx:
        if ctx.state.current_state != "scanning":
            ctx.state.transition("scanning", "Starting scan")
        result = ctx.orchestrator.run_scan(ctx.job)

        # Transition state BEFORE dispatching downstream to prevent orphaned tasks.
        # If transition fails, no task is dispatched and engagement correctly stays failed.
        try:
            ctx.state.transition("analyzing", "Scan complete")
        except Exception as e:
            logger.error("Failed to transition to analyzing for engagement=%s: %s", engagement_id, e, exc_info=True)
            ctx.state.transition("failed", f"State transition failed: {e}")
            return result
        try:
            analyze_task = app.send_task(
                "tasks.analyze.run_analysis",
                args=[engagement_id, budget, ctx.trace_id],
            )
            result["analysis_task_id"] = analyze_task.id
            slog.dispatch("analyze", task_id=analyze_task.id)
        except Exception as e:
            logger.error("Failed to enqueue analysis for engagement=%s: %s", engagement_id, e, exc_info=True)
            ctx.state.transition("failed", f"Failed to dispatch analysis: {e}")

        return result


@app.task(bind=True, name="tasks.scan.deep_scan")
def deep_scan(self, engagement_id: str, targets: list, budget: dict, trace_id: str = None):
    """
    Execute deep scanning on specific targets
    """
    from tasks.utils import fetch_engagement_scan_options
    from utils.logging_utils import ScanLogger

    opts = fetch_engagement_scan_options(engagement_id)
    slog = ScanLogger("deep_scan", engagement_id=engagement_id)
    slog.phase_header("DEEP SCAN", targets=f"{len(targets)} target(s)")

    job_extra = {
        "targets": targets,
        "budget": budget,
        "agent_mode": opts["agent_mode"],
        "scan_mode": opts["scan_mode"],
        "aggressiveness": opts["aggressiveness"],
        "bug_bounty_mode": opts.get("bug_bounty_mode", False),
    }
    with task_context(self, engagement_id, "deep_scan",
                      job_extra=job_extra,
                      trace_id=trace_id) as ctx:
        return ctx.orchestrator.run_scan(ctx.job)


@app.task(bind=True, name="tasks.scan.auth_focused_scan")
def auth_focused_scan(self, engagement_id: str, endpoints: list, budget: dict, trace_id: str = None):
    """
    Execute authentication-focused scanning
    """
    from tasks.utils import fetch_engagement_scan_options
    from utils.logging_utils import ScanLogger

    opts = fetch_engagement_scan_options(engagement_id)
    slog = ScanLogger("auth_focused_scan", engagement_id=engagement_id)
    slog.phase_header("AUTH FOCUSED SCAN", endpoints=f"{len(endpoints)} endpoint(s)")

    job_extra = {
        "endpoints": endpoints,
        "budget": budget,
        "agent_mode": opts["agent_mode"],
        "scan_mode": opts["scan_mode"],
        "aggressiveness": opts["aggressiveness"],
        "bug_bounty_mode": opts.get("bug_bounty_mode", False),
    }
    with task_context(self, engagement_id, "auth_focused_scan",
                      job_extra=job_extra,
                      trace_id=trace_id) as ctx:
        return ctx.orchestrator.run_scan(ctx.job)
