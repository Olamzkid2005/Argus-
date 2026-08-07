"""Local mode helpers for the Argus CLI — SQLite backend, orchestrator setup, phase runner."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("cli.local_mode")

_VERIFIABLE_FINDING_TYPES = frozenset({
    "sqli", "sql_injection", "sql-injection",
    "xss", "cross-site-scripting", "cross_site_scripting",
    "open-redirect", "open_redirect", "openredirect",
})

_VERIFIER_CONFIDENCE_MAP = {
    "high": 0.85,
    "medium": 0.65,
    "low": 0.35,
}

def _setup_local_mode(db_path: str) -> tuple[Any, Any]:
    """Create SQLite-backed repositories for standalone mode.

    Args:
        db_path: Path to SQLite database file (":memory:" for in-memory).

    Returns:
        Tuple of (EngagementRepository, FindingRepository) that use SQLite.
    """
    from database.sqlite_backend import SQLiteEngagementRepo, SQLiteFindingRepo

    eng_repo = SQLiteEngagementRepo(db_path)
    finding_repo = SQLiteFindingRepo(db_path)
    return eng_repo, finding_repo


def _apply_local_mode(local: bool, db_path: str) -> str:
    """Apply local/standalone mode environment configuration.

    When --local is active:
      1. ARGUS_LOCAL_MODE=1 is set so all components know Redis is unavailable
      2. A persistent db_path is ensured (defaults to ~/.argus/assessments.db)

    Args:
        local: Whether --local flag was passed.
        db_path: The current db_path (may be None).

    Returns:
        The resolved db_path to use.
    """
    if local:
        os.environ["ARGUS_LOCAL_MODE"] = "1"
        if not db_path:
            db_dir = Path.home() / ".argus" / "assessments"
            db_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(db_dir / "assessments.db")
        logger.info("Local mode: assessments use SQLite at %s", db_path)
    return db_path or ":memory:"


def _get_orchestrator(
    engagement_id: str,
    db_path: str | None = None,
    trace_id: str | None = None,
) -> Any:
    """Get an Orchestrator instance for standalone mode.

    Overrides DATABASE_URL to None so the orchestrator skips Postgres
    initialization and uses our injected repos instead.

    Args:
        engagement_id: Engagement UUID.
        db_path: Path to SQLite database (None = use :memory:).
        trace_id: Optional trace ID for observability.

    Returns:
        Configured Orchestrator instance.
    """
    from orchestrator_pkg.orchestrator import Orchestrator

    # Ensure no DATABASE_URL is set (orchestrator will use None repos)
    old_db_url = os.environ.pop("DATABASE_URL", None)

    orch = Orchestrator(engagement_id=engagement_id, trace_id=trace_id)

    # Restore DATABASE_URL if it existed (for other components)
    if old_db_url is not None:
        os.environ["DATABASE_URL"] = old_db_url

    # Override repos with SQLite backends
    if db_path:
        eng_repo, finding_repo = _setup_local_mode(db_path)
        orch.engagement_repo = eng_repo
        orch.finding_repo = finding_repo

    return orch


def _run_phases(
    orch: Any,
    target: str,
    *,
    engagement_id: str,
    finding_repo: Any,
    aggressiveness: str,
    output_format: str,
    phases: tuple[str, ...] | list[str],
    phase_results: list[dict] | None = None,
    cp_mgr: Any | None = None,
    llm_refine: bool = False,
    trace_id: str | None = None,
) -> tuple[int, list[dict]]:
    """Run assessment phases with coverage gating, checkpointing, and LLM refiner.

    Shared helper extracted from :func:`cmd_assess` and :func:`cmd_resume`.
    Handles the core phase execution loop including:
    - Coverage gate checks (skip phases with no findings)
    - Job construction per phase
    - Orchestrator dispatch
    - Checkpoint save after each completed phase
    - LLM-driven replanning between phases
    - Graceful handling of phase failures

    Args:
        orch: Orchestrator instance (persists across all phases).
        target: Target URL being assessed.
        engagement_id: Engagement UUID.
        finding_repo: Finding repository for saving/loading findings.
        aggressiveness: Scan aggressiveness level.
        output_format: Output format for the report phase.
        phases: Ordered phases to run (e.g. ``("recon", "scan", "analyze", "report")``).
        phase_results: Accumulated phase results from previous runs (for resume).
        cp_mgr: Optional checkpoint manager for crash recovery.
        llm_refine: Whether to run LLM-driven replanning after recon and scan.
        trace_id: Optional trace ID for observability.

    Returns:
        Tuple of ``(exit_code, phase_results)`` where ``exit_code`` is 0 on
        success and 1 if the recon phase failed (critical blocker).
    """
    phase_results = phase_results or []
    _llm_next_caps: list[str] | None = None
    _llm_refiner_available = False

    try:
        from reporting.llm_refiner import llm_replan_from_findings as _llm_refiner
        _llm_refiner_available = True
    except ImportError:
        pass

    for phase_name in phases:
        # ── Coverage gate: check if we should continue ──────────
        # Always run report phase regardless of previous results
        if phase_results and phase_name != "report":
            try:
                planner = getattr(orch, "_adaptive_planner", None)
                adaptive_plan = getattr(orch, "_adaptive_plan", None)
                if planner and adaptive_plan and hasattr(planner, "should_continue"):
                    should_continue = planner.should_continue(
                        plan=adaptive_plan,
                        phase_results=phase_results,
                    )
                    if not should_continue:
                        logger.info(
                            "Coverage gate: stopping before %s "
                            "(no findings from previous phase(s))",
                            phase_name,
                        )
                        break
            except Exception:
                logger.debug("Coverage gate check failed", exc_info=True)

        logger.info("=== Phase: %s ===", phase_name)

        # Build job dict for the phase, injecting any LLM-suggested capabilities
        job: dict[str, Any] = {
            "type": phase_name,
            "targets": [target],
            "target": target,
            "engagement_id": engagement_id,
            "scope": {"mode": "allowlist", "allowed_targets": [target]},
            "aggressiveness": aggressiveness,
            "agent_mode": False,
        }
        if _llm_next_caps:
            job["required_capabilities"] = _llm_next_caps
            _llm_next_caps = None

        if phase_name == "scan":
            job["recon_context"] = getattr(orch, "_recon_context", None)
            job["auth_config"] = {}
            job["budget"] = {}

        if phase_name == "analyze":
            job["phase"] = "scan"

        if phase_name == "report":
            job["format"] = output_format

        try:
            result = orch.run(job)
            status = result.get("status", "unknown")
            findings_count = result.get("findings_count", 0)
            phase_results.append({
                "phase": phase_name,
                "findings_count": findings_count,
                "status": status,
            })
            logger.info(
                "Phase %s: %s (%d findings)",
                phase_name, status, findings_count,
            )

            # ── Save checkpoint after successful phase ─────────────
            if cp_mgr is not None and status == "completed":
                try:
                    cp_mgr.save_checkpoint(
                        engagement_id,
                        phase_name,
                        {
                            "target": target,
                            "engagement_id": engagement_id,
                            "trace_id": trace_id,
                            "aggressiveness": aggressiveness,
                            "phase_results": phase_results,
                            "findings_count": findings_count,
                            "format": output_format,
                        },
                    )
                except Exception:
                    logger.debug("Checkpoint save failed (non-fatal)", exc_info=True)

            # ── LLM refiner: suggest next capabilities ──────────────
            if (
                _llm_refiner_available
                and llm_refine
                and status == "completed"
                and phase_name in ("recon", "scan")
            ):
                try:
                    all_findings, _ = finding_repo.get_findings_by_engagement(
                        engagement_id, limit=100
                    )
                    refiner_result = _llm_refiner(
                        engagement_id=engagement_id,
                        phase=phase_name,
                        target=target,
                        findings=all_findings,
                    )
                    if refiner_result.get("stop", False):
                        logger.info(
                            "LLM refiner suggests stopping: %s",
                            refiner_result.get("reasoning", ""),
                        )
                        _llm_next_caps = []
                    else:
                        _llm_next_caps = refiner_result.get("next_capabilities", [])
                        if _llm_next_caps:
                            logger.info("LLM refiner suggests: %s", _llm_next_caps)
                except Exception:
                    logger.debug("LLM refiner failed", exc_info=True)

            # ── Auto-verify low-confidence findings after scan ─────────
            if status == "completed" and phase_name == "scan":
                _auto_verify_findings(finding_repo, engagement_id)

            # ── Hypothesis-driven phase activation after scan ───────────
            if status == "completed" and phase_name == "scan":
                try:
                    from orchestrator_pkg.planning.hypothesis_planning_bridge import (
                        apply_hypothesis_engine,
                    )
                    all_findings, _ = finding_repo.get_findings_by_engagement(
                        engagement_id, limit=500
                    )
                    adaptive_plan = getattr(orch, "_adaptive_plan", None)
                    if adaptive_plan is not None and all_findings:
                        hypotheses = apply_hypothesis_engine(
                            adaptive_plan, all_findings, engagement_id
                        )
                        if hypotheses:
                            logger.info(
                                "Hypothesis engine: %d hypothesis(es) generated "
                                "from %d finding(s)",
                                len(hypotheses),
                                len(all_findings),
                            )
                except Exception:
                    logger.debug("Hypothesis integration failed", exc_info=True)

        except Exception as e:
            logger.error("Phase %s failed: %s", phase_name, e)
            phase_results.append({
                "phase": phase_name,
                "findings_count": 0,
                "status": "failed",
            })
            if phase_name == "recon":
                logger.error("Cannot continue — recon phase failed")
                return 1, phase_results
            continue

    return 0, phase_results


def _auto_verify_findings(
    finding_repo: Any,
    engagement_id: str,
    confidence_threshold: float = 0.7,
    max_to_verify: int = 10,
) -> None:
    """Auto-verify low-confidence findings after scan phase.

    Finds findings below the confidence threshold with known verifiable
    finding types (SQLi, XSS, open redirect), re-tests them via the
    finding verifier, and promotes/rejects them based on results.

    This is the CLI/local mode equivalent of the orchestration layer's
    ``run_verification()`` method, but uses the existing SQLite repos and
    finding verifier directly.

    Args:
        finding_repo: SQLite finding repository.
        engagement_id: Engagement UUID.
        confidence_threshold: Only verify findings below this confidence.
        max_to_verify: Max findings to verify per engagement.
    """
    # Verifiable finding types (ones with registered verifiers)
    verifiable_types = _VERIFIABLE_FINDING_TYPES

    # Priority mapping: verifier confidence → new confidence score
    _VERIFIER_CONFIDENCE_MAP = {
        "high": 0.85,
        "medium": 0.65,
        "low": 0.35,
    }

    try:
        # Load all findings for this engagement
        findings, total = finding_repo.get_findings_by_engagement(
            engagement_id, limit=1000
        )

        # Filter to low-confidence, verifiable findings
        to_verify = [
            f for f in findings
            if (f.get("confidence") or 0) < confidence_threshold
            and (f.get("type") or "").lower().replace("-", "_").replace(" ", "_") in verifiable_types
        ]

        if not to_verify:
            logger.info(
                "Auto-verify: no low-confidence verifiable findings (%d total)",
                total,
            )
            return

        # Limit to max_to_verify
        to_verify = to_verify[:max_to_verify]

        logger.info(
            "Auto-verify: verifying %d low-confidence finding(s) "
            "(confidence < %.2f)...",
            len(to_verify),
            confidence_threshold,
        )

        import asyncio

        async def _run_verifications() -> list[dict]:
            """Run all verifications concurrently."""
            from tools.finding_verifier import verify_finding as _vf

            results = await asyncio.gather(
                *(_vf(dict(f), engagement_id=engagement_id) for f in to_verify),
                return_exceptions=True,
            )
            return results

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            import threading

            results_container: list = []
            done_event = threading.Event()

            def _run_in_thread():
                inner = asyncio.new_event_loop()
                try:
                    res = inner.run_until_complete(_run_verifications())
                    results_container.extend(res if isinstance(res, list) else [res])
                finally:
                    inner.close()
                    done_event.set()

            thread = threading.Thread(target=_run_in_thread, daemon=True)
            thread.start()
            thread.join(timeout=60)
            results = results_container
        else:
            results = asyncio.run(_run_verifications())

        # Process verification results
        verified_count = 0
        confirmed_count = 0
        rejected_count = 0

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.debug(
                    "Auto-verify failed for finding %s: %s",
                    to_verify[i].get("id", "?")[:8],
                    result,
                )
                continue

            if i >= len(to_verify):
                break

            original = to_verify[i]
            verification = result.get("verification", {})
            verified = verification.get("verified", False)
            verifier_confidence = verification.get("confidence", "low")

            # Determine new confidence based on verifier result
            new_confidence = _VERIFIER_CONFIDENCE_MAP.get(
                verifier_confidence,
                0.35,
            )

            try:
                from tools.verification.finding_promoter import promote_finding

                promoted = promote_finding(
                    original,
                    confidence=min(new_confidence, 1.0),
                    reproduced=bool(verified),
                )

                if promoted.get("status") == "CONFIRMED":
                    confirmed_count += 1
                elif promoted.get("status") == "REJECTED":
                    rejected_count += 1

                # Update finding in SQLite (use original source_tool so
                # the upsert matches the existing finding's UNIQUE constraint
                # on (engagement_id, endpoint, type, source_tool))
                finding_repo.create_finding(
                    engagement_id=engagement_id,
                    finding_type=original.get("type", ""),
                    severity=original.get("severity", "INFO"),
                    endpoint=original.get("endpoint", ""),
                    evidence={
                        **(original.get("evidence") or {}),
                        "verification": verification,
                        "verification_status": promoted.get("status", "UNKNOWN"),
                    },
                    confidence=min(new_confidence, 1.0),
                    source_tool=original.get("source_tool", "verification"),
                )

                verified_count += 1
            except Exception as e:
                logger.debug(
                    "Failed to promote finding %s: %s",
                    original.get("id", "?")[:8],
                    e,
                )

        if verified_count > 0:
            logger.info(
                "Auto-verify complete: %d verified, "
                "%d confirmed, %d rejected",
                verified_count,
                confirmed_count,
                rejected_count,
            )
        else:
            logger.info(
                "Auto-verify: no findings could be verified "
                "(verifiers may require network access to target)"
            )

    except ImportError as e:
        logger.debug("Auto-verify unavailable: %s", e)
    except Exception as e:
        logger.debug("Auto-verify failed: %s", e)


def _output_results(engagement_id: str, target: str, finding_repo: Any, output_path: str | None) -> None:
    """Fetch findings and print/save results."""
    findings, total = finding_repo.get_findings_by_engagement(engagement_id, limit=1000)
    summary = finding_repo.get_summary_by_engagement(engagement_id)

    output = {
        "engagement_id": engagement_id,
        "target": target,
        "status": "completed",
        "total_findings": total,
        "summary": summary,
        "findings": findings,
    }

    if output_path:
        with open(output_path, "w") as f:
            json.dump(output, f, indent=2, default=str)
        logger.info("Results written to %s", output_path)
    else:
        print(json.dumps(output, indent=2, default=str))


def _store_coverage_report(orch: Any, eng_repo: Any, engagement_id: str) -> None:
    """Capture and store adaptive plan coverage report in engagement metadata."""
    try:
        if (
            hasattr(orch, "_adaptive_plan")
            and orch._adaptive_plan is not None
            and hasattr(orch._adaptive_plan, "get_coverage_report")
        ):
            coverage = orch._adaptive_plan.get_coverage_report()
            existing_metadata: dict = {}
            try:
                existing = eng_repo.find_by_id(engagement_id)
                if existing and existing.get("metadata"):
                    raw = existing["metadata"]
                    if isinstance(raw, str):
                        existing_metadata = json.loads(raw)
                    elif isinstance(raw, dict):
                        existing_metadata = raw
            except Exception:
                pass
            existing_metadata["coverage_report"] = coverage
            eng_repo.update_by_id(engagement_id, {"metadata": existing_metadata})
            pct = coverage.get("coverage_pct", 0) * 100
            logger.info(
                "Phase coverage: %d/%d activated (%.0f%%)",
                coverage.get("activated_count", 0),
                coverage.get("total_phases", 0),
                pct,
            )
    except Exception:
        logger.debug("Could not capture coverage report", exc_info=True)



def _run_startup_health_check() -> None:
    """Run a lightweight startup health check for local mode.

    Probes critical tools in parallel to warn if they're missing.
    This is a best-effort warning only — it does not block execution.
    Uses a shorter timeout (5s) than the full health command (10s).
    """
    try:
        from tool_core.health_checker import ToolHealthChecker

        checker = ToolHealthChecker(probe_timeout=5)

        # Check critical tools in parallel (fast probe, max 5s)
        critical_tools = ["nuclei", "httpx", "nmap", "subfinder", "katana", "whatweb"]
        report = checker.check_all(tool_names=critical_tools, max_workers=6)
        missing = [r.name for r in report.unavailable]

        if missing:
            logger.warning(
                "Startup: %d critical tool(s) missing from PATH: %s. "
                "Assessment will gracefully degrade. "
                "Run 'argus health' for full tool status.",
                len(missing),
                ", ".join(missing),
            )
    except ImportError:
        pass  # Health checker module not available
    except Exception:
        logger.debug("Startup health check failed", exc_info=True)
