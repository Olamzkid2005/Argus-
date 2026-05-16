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
              agent_mode: bool = True, scan_mode: str | None = None, aggressiveness: str | None = None,
              bug_bounty_mode: bool | None = None, prev_engagement_id: str | None = None):
    """
    Execute reconnaissance phase for an engagement

    Args:
        engagement_id: Engagement UUID
        target: Target URL
        budget: Budget config dict
        trace_id: Optional trace ID
        agent_mode: Enable LLM agent mode
        scan_mode: Engagement scan_mode (from job / platform)
        aggressiveness: Recon/scan aggressiveness string
        bug_bounty_mode: Whether engagement is in bug-bounty-style mode
        prev_engagement_id: Previous engagement ID for diff engine (scheduled scans)
    """
    from utils.logging_utils import ScanLogger
    slog = ScanLogger("recon", engagement_id=engagement_id)

    # Forward prev_engagement_id through the chain via budget
    if prev_engagement_id:
        budget = dict(budget)
        budget["prev_engagement_id"] = prev_engagement_id

    slog.phase_header("RECON PHASE", target=target, agent_mode=agent_mode)

    job_extra = {"target": target, "budget": budget, "agent_mode": agent_mode}
    if scan_mode is not None:
        job_extra["scan_mode"] = scan_mode
    if aggressiveness is not None:
        job_extra["aggressiveness"] = aggressiveness
    if bug_bounty_mode is not None:
        job_extra["bug_bounty_mode"] = bug_bounty_mode

    with task_context(self, engagement_id, "recon",
                      job_extra=job_extra,
                      trace_id=trace_id, current_state="created") as ctx:
        ctx.state.transition("recon", "Starting reconnaissance")
        result = ctx.orchestrator.run_recon(ctx.job)

        # Dispatch asset_discovery (non-critical — only a warning on failure,
        # doesn't abort the scan)
        try:
            asset_task = app.send_task(
                'tasks.asset_discovery.run_asset_discovery',
                args=[engagement_id, target, ctx.trace_id],
                countdown=5,
            )
            slog.dispatch("asset_discovery", task_id=asset_task.id)
        except Exception as e:
            logger.warning("Failed to enqueue asset discovery for %s: %s", engagement_id, e)

        # Dispatch scan BEFORE transitioning state. If dispatch fails the
        # engagement transitions directly to "failed" — no orphaned state.
        # If dispatch succeeds, the scan task itself transitions to "scanning"
        # (see scan.py:69-70), so there's no gap.
        try:
            scan_task = app.send_task(
                'tasks.scan.run_scan',
                args=[engagement_id, [target], budget, ctx.trace_id, agent_mode, scan_mode, aggressiveness, bug_bounty_mode],
            )
            slog.dispatch("scan", task_id=scan_task.id)
        except Exception as e:
            logger.error("Failed to enqueue scan for engagement=%s: %s", engagement_id, e, exc_info=True)
            ctx.state.safe_transition("failed", f"Failed to dispatch scan: {e}")
            return {"phase": "recon", "status": "failed", "reason": "scan_dispatch_failed"}

        # Save recon context AFTER scan dispatch so a crash between dispatch
        # and save does not leave the engagement stuck in "recon" — the scan
        # task handles a missing context gracefully (falls back to deterministic).
        if result.get("recon_context"):
            try:
                from tasks.utils import save_recon_context
                ctx_data = result["recon_context"]
                if isinstance(ctx_data, dict):
                    from models.recon_context import ReconContext
                    ctx_data = ReconContext.from_dict(ctx_data)
                save_recon_context(engagement_id, ctx_data)
                slog.info("Saved recon context for scan phase")
            except Exception as e:
                logger.warning("Failed to save recon context for %s — scan will fall back to deterministic: %s", engagement_id, e)

        # Transition state AFTER dispatch succeeds. If the process crashes
        # between dispatch and this transition, the scan task handles
        # transitioning to "scanning" itself (scan.py line 69-70).
        ctx.state.transition("scanning", "Recon complete — scan dispatched")

        return result


@app.task(bind=True, name="tasks.recon.expand_recon")
def expand_recon(self, engagement_id: str, targets: list, budget: dict, trace_id: str = None):
    """
    Expand reconnaissance with additional targets
    """
    from utils.logging_utils import ScanLogger
    slog = ScanLogger("recon_expand", engagement_id=engagement_id)

    valid_targets = [t for t in targets if t and isinstance(t, str)]
    if not valid_targets:
        slog.info("expand_recon called with empty/invalid targets, transitioning to reporting")
        logger.warning(f"expand_recon called with empty/invalid targets for engagement {engagement_id}, transitioning to reporting")
        from tasks.base import task_context
        with task_context(self, engagement_id, "recon_expand",
                          job_extra={"target": None, "targets": [], "budget": budget},
                          trace_id=trace_id, current_state="recon") as ctx:
            # Use atomic chain-transition instead of three separate commits
            # to avoid phantom intermediate states if a transition fails mid-chain.
            ctx.state.chain_transition([
                ("scanning", "No additional targets — advancing to scan"),
                ("analyzing", "No additional targets — advancing to analyze"),
                ("reporting", "No additional targets — advancing to report"),
            ])
            try:
                app.send_task('tasks.report.generate_report',
                              args=[engagement_id, ctx.trace_id, budget])
            except Exception as e:
                logger.error("Failed to enqueue report for engagement=%s: %s", engagement_id, e, exc_info=True)
                ctx.state.safe_transition("failed", f"Failed to enqueue report: {e}")
                return {"phase": "recon_expand", "status": "failed", "reason": "report_dispatch_failed", "next_state": "failed"}
        return {"phase": "recon_expand", "status": "skipped", "reason": "no_valid_targets", "next_state": "reporting"}

    slog.phase_header("EXPAND RECON", targets=f"{len(valid_targets)} targets")

    with task_context(self, engagement_id, "recon_expand",
                      job_extra={"target": valid_targets[0], "targets": valid_targets, "budget": budget},
                      trace_id=trace_id, current_state="recon") as ctx:
        result = ctx.orchestrator.run_recon(ctx.job)

        # Load scan flags from DB (expand_recon is not dispatched with full job payload)
        from tasks.utils import fetch_engagement_scan_options

        opts = fetch_engagement_scan_options(engagement_id)
        # Transition first so if it fails, no orphaned downstream task
        try:
            ctx.state.transition("scanning", "Expanded recon complete — auto-advancing to scan")
        except Exception as e:
            logger.error("Failed to transition to scanning for engagement=%s: %s", engagement_id, e, exc_info=True)
            ctx.state.safe_transition("failed", f"State transition failed: {e}")
            return result
        try:
            scan_task = app.send_task(
                'tasks.scan.run_scan',
                args=[
                    engagement_id,
                    valid_targets,
                    budget,
                    ctx.trace_id,
                    opts["agent_mode"],
                    opts["scan_mode"],
                    opts["aggressiveness"],
                    opts.get("bug_bounty_mode"),
                ],
            )
            slog.dispatch("scan", task_id=scan_task.id)
            logger.info("Dispatched scan after expand for engagement=%s (task=%s)", engagement_id, scan_task.id)
        except Exception as e:
            logger.error("Failed to enqueue scan after expand for engagement=%s: %s", engagement_id, e, exc_info=True)
            ctx.state.safe_transition("failed", f"Failed to dispatch scan: {e}")
            return result

        # Save updated recon context AFTER scan dispatch so a crash between
        # dispatch and save does not leave the engagement stuck — the scan
        # task handles a missing context gracefully (falls back to deterministic).
        if result.get("recon_context"):
            try:
                from tasks.utils import save_recon_context
                ctx_data = result["recon_context"]
                if isinstance(ctx_data, dict):
                    from models.recon_context import ReconContext
                    ctx_data = ReconContext.from_dict(ctx_data)
                save_recon_context(engagement_id, ctx_data)
                slog.info("Saved expanded recon context")
                logger.info("Saved expanded recon context for %s", engagement_id)
            except Exception as e:
                logger.warning("Failed to save expanded recon context for %s — scan will fall back to deterministic: %s", engagement_id, e)

        return result

