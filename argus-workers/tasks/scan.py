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
    auth_config: dict | None = None,
    dual_auth_config: dict | None = None,
    scope: dict | None = None,
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
        ep_count = (
            len(recon_context.live_endpoints or [])
            if (recon_context and hasattr(recon_context, "live_endpoints"))
            else 0
        )
        recon_info = f"{ep_count} endpoints" if recon_context else "none"
        slog.info("Recon context loaded: %s", recon_info)
    except Exception as e:
        logger.exception(
            "Failed to load recon context for engagement=%s: %s", engagement_id, e
        )
        recon_context = None
        # Track this failure so operators can investigate why recon context
        # was lost (expired TTL? Redis down? serialization error?)
        try:
            from dead_letter_queue import get_dlq

            get_dlq().enqueue(
                task_id="recon_context_load",
                task_name="tasks.scan.run_scan",
                args=[],
                kwargs={"engagement_id": engagement_id},
                error_message=str(e),
                error_class=type(e).__name__,
                engagement_id=engagement_id,
            )
        except Exception as dlq_e:
            logger.debug("DLQ enqueue failed for recon context load: %s", dlq_e)
        # Notify UI
        try:
            from streaming import emit_thinking

            emit_thinking(
                engagement_id, "Recon context unavailable — running deterministic scan"
            )
        except Exception:
            logger.warning(
                "Failed to emit thinking update for engagement=%s", engagement_id
            )

    # ── Binary provisioning visibility: warn loudly about missing tools ──
    # Without the external binaries the agent's tool calls fail; make that
    # operator-visible at scan start instead of silently degrading.
    try:
        _missing_tools = _check_missing_phase_tools("scan")
        if _missing_tools:
            logger.warning(
                "MISSING TOOL BINARIES (%d): %s. Agent tool calls for these will "
                "fail loudly with NOT_INSTALLED status. Install via: "
                "python scripts/install_tools.py",
                len(_missing_tools),
                ", ".join(sorted(_missing_tools)),
            )
    except Exception as _tools_err:
        logger.debug("Tool availability check failed (non-fatal): %s", _tools_err)

    mode = "agent" if agent_mode else "deterministic"
    slog.phase_header("SCAN PHASE", targets=f"{len(targets)} target(s)", mode=mode)

    job_extra = {
        "targets": targets,
        "budget": budget,
        "agent_mode": agent_mode,
        "recon_context": recon_context,
        "auth_config": auth_config or {},
        "dual_auth_config": dual_auth_config,
    }
    if scan_mode is not None:
        job_extra["scan_mode"] = scan_mode
    if aggressiveness is not None:
        job_extra["aggressiveness"] = aggressiveness
    if bug_bounty_mode is not None:
        job_extra["bug_bounty_mode"] = bug_bounty_mode
    if scope is not None:
        job_extra["scope"] = scope

    with task_context(
        self, engagement_id, "scan", job_extra=job_extra, trace_id=trace_id
    ) as ctx:
        # Idempotency check: if engagement has already progressed past scanning
        # (e.g. Celery retry delivered duplicate task), skip immediately.
        # Query the actual DB state rather than relying on client-side current_state.
        from tasks.utils import get_engagement_state

        _db_state = get_engagement_state(engagement_id, ctx.db_conn_string)
        if _db_state in ("analyzing", "reporting", "complete", "failed"):
            logger.info(
                "Engagement %s already past 'scanning' (state=%s) — skipping duplicate scan task",
                engagement_id,
                _db_state,
            )
            return {"phase": "scan", "status": "skipped", "reason": f"already_{_db_state}"}

        if ctx.state.current_state != "scanning":
            ctx.state.transition("scanning", "Starting scan")
        result = ctx.orchestrator.run_scan(ctx.job)

        # ── Gap 3.x: Exploit chain checkpoint ──
        # After scan completes, check the attack graph for vulnerability chains
        # that warrant an immediate exploitation phase before analysis.
        # If chain plans are found with CRITICAL severity, dispatch exploitation.
        # run_scan() returns findings_count (int) not the findings list, so
        # handle_get_attack_graph loads findings from the database.
        _needs_exploitation = False
        _findings_count = result.get("findings_count", 0)
        if _findings_count > 0:
            try:
                from mcp_server import get_mcp_server

                _mcp = get_mcp_server()
                _attack_graph_result = _mcp.handle_get_attack_graph({
                    "engagement_id": engagement_id,
                    # No inline findings — handle_get_attack_graph loads from DB
                })
                _chain_plans = _attack_graph_result.get("chain_plans", [])
                if _chain_plans:
                    # Check if any chain plan is CRITICAL/HIGH severity
                    _critical_chains = [
                        c for c in _chain_plans
                        if c.get("severity", "") in ("CRITICAL", "HIGH")
                    ]
                    if _critical_chains:
                        _needs_exploitation = True
                        slog.info(
                            "Attack graph detected %d CRITICAL/HIGH chain(s) among %d "
                            "findings — dispatching exploitation phase before analysis",
                            len(_critical_chains),
                            _findings_count,
                        )
                        for _chain in _critical_chains:
                            slog.info(
                                "  Chain: %s (severity=%s, risk_score=%.2f) — %s",
                                _chain.get("name", "unknown"),
                                _chain.get("severity", ""),
                                _chain.get("risk_score", 0.0),
                                _chain.get("description", "")[:100],
                            )
            except Exception as _chain_err:
                logger.debug(
                    "Attack graph chain detection failed (non-fatal): %s", _chain_err
                )

        # ── Gap closure: automatic auth-focused scan trigger ──
        # Recon records login pages and auth endpoints on the ReconContext
        # (has_login_page / auth_endpoints). When an auth surface exists, dive
        # into exactly those endpoints with the auth tooling (jwt_tool, dual
        # auth, session analysis, ...) before analysis. tasks.scan.auth_focused_scan
        # chains into analyze itself, so we return here without dispatching
        # analyze. The budget flag prevents re-triggering on steering
        # re-invocations. Auth takes precedence over the generic deep-scan
        # pass below: login flows are the highest-value attack surface.
        if (
            not _needs_exploitation
            and not budget.get("auth_focused_dispatched")
        ):
            try:
                _auth_endpoints = _detect_auth_endpoints(engagement_id, redis_url)
            except Exception as _auth_err:
                logger.warning(
                    "Auth endpoint detection failed (non-fatal): %s", _auth_err
                )
                _auth_endpoints = []
            if _auth_endpoints:
                budget["auth_focused_dispatched"] = True
                slog.info(
                    "Auth surface detected (%d login/auth endpoint(s)) — dispatching auth_focused_scan: %s",
                    len(_auth_endpoints),
                    _auth_endpoints[:3],
                )
                try:
                    _auth_task = app.send_task(
                        "tasks.scan.auth_focused_scan",
                        args=[engagement_id, _auth_endpoints, budget, ctx.trace_id],
                    )
                    result["auth_focused_dispatched"] = True
                    result["auth_focused_task_id"] = _auth_task.id
                    result["next_state"] = "auth_focused_scan"
                    slog.dispatch("auth_focused_scan", task_id=_auth_task.id)
                    return result
                except Exception as e:
                    logger.exception(
                        "Failed to enqueue auth_focused_scan for engagement=%s: %s",
                        engagement_id,
                        e,
                    )
                    # Fall through to the deep-scan / analyze dispatch below.

        # ── Gap closure: automatic deep-scan trigger ──
        # When the scan found high-value endpoints (CRITICAL/HIGH findings) but
        # no exploitable chain, deepen the engagement against exactly those
        # endpoints before analysis. tasks.scan.deep_scan chains into analyze
        # itself, so we return here without dispatching analyze. The budget
        # flag prevents re-triggering on steering re-invocations.
        if not _needs_exploitation and not budget.get("deep_scan_dispatched"):
            try:
                _priority_endpoints = _detect_high_value_endpoints(
                    engagement_id, ctx.db_conn_string
                )
            except Exception as _deep_err:
                logger.warning(
                    "High-value endpoint detection failed (non-fatal): %s", _deep_err
                )
                _priority_endpoints = []
            if _priority_endpoints:
                budget["deep_scan_dispatched"] = True
                slog.info(
                    "High-value endpoint(s) detected — dispatching deep_scan: %s",
                    _priority_endpoints[:3],
                )
                try:
                    _deep_task = app.send_task(
                        "tasks.scan.deep_scan",
                        args=[engagement_id, _priority_endpoints, budget, ctx.trace_id],
                    )
                    result["deep_scan_dispatched"] = True
                    result["deep_scan_task_id"] = _deep_task.id
                    result["next_state"] = "deep_scan"
                    slog.dispatch("deep_scan", task_id=_deep_task.id)
                    return result
                except Exception as e:
                    logger.exception(
                        "Failed to enqueue deep_scan for engagement=%s: %s",
                        engagement_id,
                        e,
                    )
                    # Fall through to the normal analyze dispatch below.

        if _needs_exploitation:
            # Insert exploitation phase before analysis
            try:
                ctx.state.transition(
                    "exploitation",
                    "Attack chain(s) detected — dispatching exploitation phase",
                )
            except Exception as e:
                logger.exception(
                    "Failed to transition to exploitation for engagement=%s: %s",
                    engagement_id,
                    e,
                )
                ctx.state.safe_transition(
                    "failed", f"State transition failed: {e}"
                )
                result["status"] = "failed"
                result["reason"] = "exploitation_transition_failed"
                return result
            try:
                app.send_task(
                    "tasks.post_exploit.run_post_exploit",
                    args=[engagement_id, budget, ctx.trace_id],
                )
                slog.info(
                    "Exploitation phase dispatched for engagement %s",
                    engagement_id,
                )
            except Exception as e:
                logger.exception(
                    "Failed to enqueue exploitation for engagement=%s: %s",
                    engagement_id,
                    e,
                )
                ctx.state.safe_transition(
                    "failed",
                    f"Failed to enqueue exploitation: {e}",
                )
                result["status"] = "failed"
                result["reason"] = "exploitation_dispatch_failed"
                return result
            # After exploitation completes, the exploitation task transitions to
            # "reporting" and dispatches report generation directly (see post_exploit.py).
            # The analyze phase is skipped in this path because exploitation findings
            # are self-contained (credential replay, internal probing) and the report
            # generation covers them directly. If LLM analysis is needed, add an
            # analyze dispatch here before post_exploit.
            return result

        # Transition state BEFORE dispatching downstream to prevent orphaned tasks.
        # If transition fails, no task is dispatched and engagement correctly stays failed.
        try:
            ctx.state.transition("analyzing", "Scan complete")
        except Exception as e:
            logger.exception(
                "Failed to transition to analyzing for engagement=%s: %s",
                engagement_id,
                e,
            )
            ctx.state.safe_transition("failed", f"State transition failed: {e}")
            result["status"] = "failed"
            result["reason"] = "state_transition_failed"
            return result
        try:
            analyze_task = app.send_task(
                "tasks.analyze.run_analysis",
                args=[engagement_id, budget, ctx.trace_id],
                kwargs={"bug_bounty_mode": bug_bounty_mode}
                if bug_bounty_mode is not None
                else {},
            )
            result["analysis_task_id"] = analyze_task.id
            slog.dispatch("analyze", task_id=analyze_task.id)
        except Exception as e:
            logger.exception(
                "Failed to enqueue analysis for engagement=%s: %s", engagement_id, e
            )
            ctx.state.safe_transition("failed", f"Failed to dispatch analysis: {e}")
            result["status"] = "failed"
            result["reason"] = "analyze_dispatch_failed"

        return result


def _detect_high_value_endpoints(
    engagement_id: str, db_conn_string: str | None
) -> list[str]:
    """Return CRITICAL/HIGH-severity endpoints that warrant a deep scan.

    Loads findings from the database and uses IntelligenceEngine's
    high-value detection so the deepening decision is signal-driven rather
    than operator-steered. Returns [] when nothing warrants deepening.
    """
    from database.repositories.finding_repository import FindingRepository
    from intelligence_engine import IntelligenceEngine

    if not db_conn_string:
        return []
    repo = FindingRepository(db_conn_string)
    findings, _total = repo.get_findings_by_engagement(engagement_id, limit=500)
    if not findings:
        return []
    engine = IntelligenceEngine()
    if not engine.detect_high_value_targets(findings):
        return []
    return engine.get_priority_endpoints(findings)


def _detect_auth_endpoints(
    engagement_id: str, redis_url: str | None = None, max_endpoints: int = 5
) -> list[str]:
    """Return login/auth endpoints recorded by recon that warrant an auth-focused scan.

    Signal source: the persisted ``ReconContext`` (populated by
    ``orchestrator_pkg.recon`` with ``has_login_page`` / ``auth_endpoints``).
    Falls back to the live endpoints when a login page was detected but the
    exact auth URLs were not extracted, so the trigger still fires. Returns
    ``[]`` when recon found no auth surface (or recon data is unavailable),
    making this strictly non-fatal.

    Args:
        engagement_id: Engagement UUID.
        redis_url: Redis URL to read the ReconContext from. Pass the same
            value run_scan resolves (``REDIS_URL`` env) so the signal is read
            from the same store the recon phase wrote to.
        max_endpoints: Upper bound on returned endpoints (deduped).
    """
    from tasks.utils import load_recon_context

    try:
        recon = load_recon_context(engagement_id, redis_url)
    except Exception as e:
        logger.debug(
            "Recon context unavailable for auth detection (non-fatal): %s", e
        )
        return []
    if not recon:
        return []

    has_login = bool(getattr(recon, "has_login_page", False))
    auth_endpoints = list(getattr(recon, "auth_endpoints", None) or [])
    if not auth_endpoints:
        if has_login:
            # Login page detected but the exact URL wasn't extracted —
            # auth-focus the live endpoints instead of missing the trigger.
            auth_endpoints = list(getattr(recon, "live_endpoints", None) or [])
        else:
            return []

    seen: set[str] = set()
    endpoints: list[str] = []
    for ep in auth_endpoints:
        ep = (ep or "").strip()
        if not ep or ep in seen:
            continue
        seen.add(ep)
        endpoints.append(ep)
        if len(endpoints) >= max_endpoints:
            break
    return endpoints


def _check_missing_phase_tools(phase: str) -> list[str]:
    """Return tool names for *phase* whose binaries are unavailable.

    Used to warn loudly at scan start so operators notice missing external
    binaries instead of the agent silently degrading to fallback scanners.
    """
    from tool_core.registry import ToolRegistry
    from tool_definitions import get_tools_for_phase

    try:
        tools = get_tools_for_phase(phase)
    except Exception:
        return []
    if not tools:
        return []
    registry = ToolRegistry()
    missing = []
    for tool in tools:
        name = getattr(tool, "name", None)
        if name and not registry.is_available(name):
            missing.append(name)
    return missing


@app.task(bind=True, name="tasks.scan.deep_scan", soft_time_limit=2400, time_limit=3600)
def deep_scan(
    self,
    engagement_id: str,
    targets: list,
    budget: dict,
    trace_id: str = None,
    auth_config: dict | None = None,
):
    """
    Execute deep scanning on specific targets
    """
    from utils.logging_utils import ScanLogger

    slog = ScanLogger("deep_scan", engagement_id=engagement_id)

    # Fetch scan options INSIDE task_context so error handling uses the
    # DistributedLock and correct state machine (bug #15 fix).
    with task_context(
        self,
        engagement_id,
        "deep_scan",
        job_extra={
            "targets": targets,
            "budget": budget,
            "auth_config": auth_config or {},
        },
        trace_id=trace_id,
    ) as ctx:
        # Idempotency check
        from tasks.utils import get_engagement_state

        _db_state = get_engagement_state(engagement_id, ctx.db_conn_string)
        if _db_state in ("analyzing", "reporting", "complete", "failed"):
            logger.info(
                "Engagement %s already past 'scanning' (state=%s) — skipping duplicate deep_scan task",
                engagement_id,
                _db_state,
            )
            return {"phase": "deep_scan", "status": "skipped", "reason": f"already_{_db_state}"}

        from tasks.utils import fetch_engagement_scan_options

        try:
            opts = fetch_engagement_scan_options(engagement_id)
        except Exception as e:
            logger.error(
                "Failed to fetch scan options for deep_scan engagement=%s: %s",
                engagement_id,
                e,
            )
            ctx.state.safe_transition("failed", f"Failed to fetch scan options: {e}")
            return {"phase": "deep_scan", "status": "failed", "reason": str(e)}

        ctx.job.update(
            {
                "agent_mode": opts["agent_mode"],
                "scan_mode": opts["scan_mode"],
                "aggressiveness": opts["aggressiveness"],
                "bug_bounty_mode": opts.get("bug_bounty_mode", False),
            }
        )

        # Ensure we record the scanning state (caller may have left us in 'recon')
        ctx.state.safe_transition("scanning", "Starting deep scan")
        slog.phase_header("DEEP SCAN", targets=f"{len(targets)} target(s)")
        result = ctx.orchestrator.run_scan(ctx.job)
        try:
            ctx.state.transition("analyzing", "Deep scan complete")
        except Exception as e:
            logger.exception(
                "Failed to transition to analyzing after deep_scan for engagement=%s: %s",
                engagement_id,
                e,
            )
            ctx.state.safe_transition("failed", f"State transition failed: {e}")
            result["status"] = "failed"
            result["reason"] = "state_transition_failed"
            return result
        try:
            analyze_task = app.send_task(
                "tasks.analyze.run_analysis",
                args=[engagement_id, budget, ctx.trace_id],
                kwargs={"bug_bounty_mode": ctx.job.get("bug_bounty_mode")},
            )
            slog.dispatch("analyze", task_id=analyze_task.id)
        except Exception as e:
            logger.exception(
                "Failed to enqueue analysis after deep_scan for engagement=%s: %s",
                engagement_id,
                e,
            )
            ctx.state.safe_transition("failed", f"Failed to dispatch analysis: {e}")
            result["status"] = "failed"
            result["reason"] = "analyze_dispatch_failed"
        return result


@app.task(
    bind=True,
    name="tasks.scan.auth_focused_scan",
    soft_time_limit=2400,
    time_limit=3600,
)
def auth_focused_scan(
    self,
    engagement_id: str,
    endpoints: list,
    budget: dict,
    trace_id: str = None,
    auth_config: dict | None = None,
):
    """
    Execute authentication-focused scanning
    """
    from utils.logging_utils import ScanLogger

    slog = ScanLogger("auth_focused_scan", engagement_id=engagement_id)

    # Fetch scan options INSIDE task_context so error handling uses the
    # DistributedLock and correct state machine (bug #15 fix).
    with task_context(
        self,
        engagement_id,
        "auth_focused_scan",
        job_extra={
            "targets": endpoints,
            "budget": budget,
            "auth_config": auth_config or {},
        },
        trace_id=trace_id,
    ) as ctx:
        # Idempotency check
        from tasks.utils import get_engagement_state

        _db_state = get_engagement_state(engagement_id, ctx.db_conn_string)
        if _db_state in ("analyzing", "reporting", "complete", "failed"):
            logger.info(
                "Engagement %s already past 'scanning' (state=%s) — skipping duplicate auth_focused_scan task",
                engagement_id,
                _db_state,
            )
            return {"phase": "auth_focused_scan", "status": "skipped", "reason": f"already_{_db_state}"}

        from tasks.utils import fetch_engagement_scan_options

        try:
            opts = fetch_engagement_scan_options(engagement_id)
        except Exception as e:
            logger.error(
                "Failed to fetch scan options for auth_focused_scan engagement=%s: %s",
                engagement_id,
                e,
            )
            ctx.state.safe_transition("failed", f"Failed to fetch scan options: {e}")
            return {"phase": "auth_focused_scan", "status": "failed", "reason": str(e)}

        ctx.job.update(
            {
                "agent_mode": opts["agent_mode"],
                "scan_mode": opts["scan_mode"],
                "aggressiveness": opts["aggressiveness"],
                "bug_bounty_mode": opts.get("bug_bounty_mode", False),
            }
        )

        # Ensure we record the scanning state (caller may have left us in 'recon')
        ctx.state.safe_transition("scanning", "Starting auth-focused scan")
        slog.phase_header("AUTH FOCUSED SCAN", endpoints=f"{len(endpoints)} endpoint(s)")
        result = ctx.orchestrator.run_scan(ctx.job)
        try:
            ctx.state.transition("analyzing", "Auth-focused scan complete")
        except Exception as e:
            logger.exception(
                "Failed to transition to analyzing after auth_focused_scan for engagement=%s: %s",
                engagement_id,
                e,
            )
            ctx.state.safe_transition("failed", f"State transition failed: {e}")
            result["status"] = "failed"
            result["reason"] = "state_transition_failed"
            return result
        try:
            analyze_task = app.send_task(
                "tasks.analyze.run_analysis",
                args=[engagement_id, budget, ctx.trace_id],
                kwargs={"bug_bounty_mode": ctx.job.get("bug_bounty_mode")},
            )
            slog.dispatch("analyze", task_id=analyze_task.id)
        except Exception as e:
            logger.exception(
                "Failed to enqueue analysis after auth_focused_scan for engagement=%s: %s",
                engagement_id,
                e,
            )
            ctx.state.safe_transition("failed", f"Failed to dispatch analysis: {e}")
            result["status"] = "failed"
            result["reason"] = "analyze_dispatch_failed"
        return result
