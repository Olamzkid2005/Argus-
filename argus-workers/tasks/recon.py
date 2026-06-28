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
    soft_time_limit=2400,  # 40 minutes for long-running recon tools
    time_limit=3600,  # 60 minutes hard limit
)
def run_recon(
    self,
    engagement_id: str,
    target: str,
    budget: dict,
    trace_id: str = None,
    agent_mode: bool = True,
    scan_mode: str | None = None,
    aggressiveness: str | None = None,
    bug_bounty_mode: bool | None = None,
    prev_engagement_id: str | None = None,
    auth_config: dict | None = None,
    dual_auth_config: dict | None = None,
):
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

    # Forward prev_engagement_id through the chain via budget.
    # Always copy so downstream consumers can rely on key presence
    # (or None) rather than testing hasattr.
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
    if auth_config is not None:
        job_extra["auth_config"] = auth_config
    if dual_auth_config is not None:
        job_extra["dual_auth_config"] = dual_auth_config

    with task_context(
        self,
        engagement_id,
        "recon",
        job_extra=job_extra,
        trace_id=trace_id,
        current_state="created",
    ) as ctx:
        # Idempotency check: if engagement has already progressed past recon
        # (e.g. Celery retry delivered duplicate task), skip immediately.
        from tasks.utils import get_engagement_state

        _db_state = get_engagement_state(engagement_id, ctx.db_conn_string)
        if _db_state in ("scanning", "analyzing", "reporting", "complete", "failed"):
            logger.info(
                "Engagement %s already past 'recon' (state=%s) — skipping duplicate recon task",
                engagement_id,
                _db_state,
            )
            return {"phase": "recon", "status": "skipped", "reason": f"already_{_db_state}"}

        ctx.state.transition("recon", "Starting reconnaissance")
        result = ctx.orchestrator.run_recon(ctx.job)

        # Dispatch asset_discovery (non-critical — only a warning on failure,
        # doesn't abort the scan)
        try:
            asset_task = app.send_task(
                "tasks.asset_discovery.run_asset_discovery",
                args=[engagement_id, target, ctx.trace_id],
                countdown=5,
            )
            slog.dispatch("asset_discovery", task_id=asset_task.id)
        except Exception as e:
            logger.warning(
                "Failed to enqueue asset discovery for %s: %s", engagement_id, e
            )

        # Save recon context BEFORE dispatching scan to eliminate race
        # condition. The orchestrator.run_recon() already persists the context
        # to Redis, but we re-save here to ensure the latest state is available
        # when the scan worker starts. If save fails, scan handles missing
        # context gracefully (falls back to deterministic).
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
                logger.exception(
                    "Failed to save recon context for %s — scan will fall back to deterministic: %s",
                    engagement_id,
                    e,
                )
                try:
                    from dead_letter_queue import get_dlq

                    get_dlq().enqueue(
                        task_id="recon_context_save",
                        task_name="tasks.recon.run_recon",
                        args=[],
                        kwargs={"engagement_id": engagement_id},
                        error_message=str(e),
                        error_class=type(e).__name__,
                        engagement_id=engagement_id,
                    )
                except Exception as dlq_e:
                    logger.debug("DLQ enqueue failed for recon context save: %s", dlq_e)

        # Dispatch scan AFTER saving context. If dispatch fails the
        # engagement transitions directly to "failed" — no orphaned state.
        try:
            scan_task = app.send_task(
                "tasks.scan.run_scan",
                args=[
                    engagement_id,
                    [target],
                    budget,
                    ctx.trace_id,
                    agent_mode,
                    scan_mode,
                    aggressiveness,
                    bug_bounty_mode,
                ],
                kwargs={
                    "auth_config": ctx.job.get("auth_config"),
                    "dual_auth_config": ctx.job.get("dual_auth_config"),
                }
                if ctx.job.get("auth_config") or ctx.job.get("dual_auth_config")
                else {},
            )
            slog.dispatch("scan", task_id=scan_task.id)
        except Exception as e:
            logger.exception(
                "Failed to enqueue scan for engagement=%s: %s", engagement_id, e
            )
            ctx.state.safe_transition("failed", f"Failed to dispatch scan: {e}")
            return {
                "phase": "recon",
                "status": "failed",
                "reason": "scan_dispatch_failed",
            }

        # Transition state AFTER dispatch succeeds. If the process crashes
        # between dispatch and this transition, the scan task handles
        # transitioning to "scanning" itself (scan.py line 69-70).
        ctx.state.transition("scanning", "Recon complete — scan dispatched")

        return result


@app.task(
    bind=True, name="tasks.recon.expand_recon", soft_time_limit=2400, time_limit=3600
)
def expand_recon(
    self, engagement_id: str, targets: list, budget: dict, trace_id: str = None
):
    """
    Expand reconnaissance with additional targets
    """
    from utils.logging_utils import ScanLogger

    slog = ScanLogger("recon_expand", engagement_id=engagement_id)

    valid_targets = [t for t in targets if t and isinstance(t, str)]
    if not valid_targets:
        slog.info(
            "expand_recon called with empty/invalid targets, transitioning to reporting"
        )
        logger.warning(
            "expand_recon called with empty/invalid targets for engagement %s, transitioning to reporting",
            engagement_id,
        )
        with task_context(
            self,
            engagement_id,
            "recon_expand",
            job_extra={"target": None, "targets": [], "budget": budget},
            trace_id=trace_id,
            current_state="recon",
        ) as ctx:
            # No targets to expand — skip scanning but still run analysis to enrich
            # existing recon findings with confidence scores and threat intel.
            # Skipping analysis would leave findings raw and unenriched in reports.
            ctx.state.chain_transition(
                [
                    ("scanning", "No additional targets — skipping scan"),
                    ("analyzing", "Running analysis enrichment on existing findings"),
                ],
                trace_id=trace_id,
            )
            try:
                app.send_task(
                    "tasks.analyze.run_analysis",
                    args=[engagement_id, budget, ctx.trace_id],
                )
            except Exception as e:
                logger.exception(
                    "Failed to enqueue analysis for engagement=%s: %s", engagement_id, e
                )
                ctx.state.safe_transition("failed", f"Failed to enqueue analysis: {e}")
                return {
                    "phase": "recon_expand",
                    "status": "failed",
                    "reason": "analysis_dispatch_failed",
                    "next_state": "failed",
                }
        return {
            "phase": "recon_expand",
            "status": "skipped_scan",
            "reason": "no_valid_targets",
            "next_state": "analyzing",
        }

    slog.phase_header("EXPAND RECON", targets=f"{len(valid_targets)} targets")

    # NOTE: chain_transition() below uses SELECT ... FOR UPDATE on the
    # engagement row while task_context holds the DistributedLock.
    # This is safe because both locks are acquired in the same order
    # (DistributedLock → DB FOR UPDATE) everywhere in the codebase.
    # If a code path were to acquire FOR UPDATE outside the DistributedLock,
    # a deadlock could occur (DistributedLock waits for FOR UPDATE, FOR UPDATE
    # waits for DistributedLock). See bug #12.
    with task_context(
        self,
        engagement_id,
        "recon_expand",
        job_extra={
            "target": valid_targets[0],
            "targets": valid_targets,
            "budget": budget,
        },
        trace_id=trace_id,
        current_state="recon",
    ) as ctx:
        result = ctx.orchestrator.run_recon(ctx.job)

        # Save updated recon context BEFORE dispatching scan to eliminate
        # race condition. The orchestrator.run_recon() already persists it
        # to Redis, but we re-save here for the expanded context.
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
                logger.exception(
                    "Failed to save expanded recon context for %s — scan will fall back to deterministic: %s",
                    engagement_id,
                    e,
                )
                try:
                    from dead_letter_queue import get_dlq

                    get_dlq().enqueue(
                        task_id="recon_context_save_expand",
                        task_name="tasks.recon.expand_recon",
                        args=[],
                        kwargs={"engagement_id": engagement_id},
                        error_message=str(e),
                        error_class=type(e).__name__,
                        engagement_id=engagement_id,
                    )
                except Exception as dlq_e:
                    logger.debug(
                        "DLQ enqueue failed for recon context save expand: %s", dlq_e
                    )

        # Load scan flags from DB (expand_recon is not dispatched with full job payload)
        from tasks.utils import fetch_engagement_scan_options

        opts = fetch_engagement_scan_options(engagement_id)
        # Transition first so if it fails, no orphaned downstream task
        try:
            ctx.state.transition(
                "scanning", "Expanded recon complete — auto-advancing to scan"
            )
        except Exception as e:
            logger.exception(
                "Failed to transition to scanning for engagement=%s: %s",
                engagement_id,
                e,
            )
            ctx.state.safe_transition("failed", f"State transition failed: {e}")
            return result

        try:
            _scan_kwargs = {}
            _auth = opts.get("auth_config") or ctx.job.get("auth_config")
            _dual = opts.get("dual_auth_config") or ctx.job.get("dual_auth_config")
            if _auth:
                _scan_kwargs["auth_config"] = _auth
            if _dual:
                _scan_kwargs["dual_auth_config"] = _dual
            scan_task = app.send_task(
                "tasks.scan.run_scan",
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
                kwargs=_scan_kwargs,
            )
            slog.dispatch("scan", task_id=scan_task.id)
            logger.info(
                "Dispatched scan after expand for engagement=%s (task=%s)",
                engagement_id,
                scan_task.id,
            )
        except Exception as e:
            logger.exception(
                "Failed to enqueue scan after expand for engagement=%s: %s",
                engagement_id,
                e,
            )
            ctx.state.safe_transition("failed", f"Failed to dispatch scan: {e}")
            return result

        return result
