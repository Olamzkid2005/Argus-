#!/usr/bin/env python3
"""Argus standalone CLI — run security assessments without Docker/Postgres/Redis.

Usage:
    # Full assessment (recon -> scan -> analyze -> report)
    argus assess https://example.com
    argus assess https://example.com --aggressiveness moderate
    argus assess https://example.com --local --output findings.json

    # Individual phases
    argus scan https://example.com --local
    argus report <engagement_id> --format json

    # Compliance reports
    argus report <engagement_id> --compliance owasp_top10
    argus report <engagement_id> --compliance pci_dss --output report.html

    # List engagements
    argus list
    argus list --local

    # Resume crashed assessment
    argus resume <engagement_id> --local

    # Cross-engagement trends
    argus trends --domain example.com --last-n-days 90

    # Tool health check
    argus health --verbose

Requires:
    - Python 3.11+
    - Assessment tools (nuclei, httpx, etc.) on PATH for full functionality
    - LLM API key for LLM-powered analysis (optional, degrades gracefully)

Modes:
    --local     Standalone mode using SQLite (no Docker/Postgres/Redis required).
                Assessments are persisted to ~/.argus/assessments/assessments.db.
    default     Uses in-memory SQLite (ephemeral, lost on exit). Use --db for
                a persistent file path without enabling local mode.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Lazy imports (expensive modules loaded only when needed)
_ORCHESTRATOR_IMPORTED = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cli")


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
                    if not planner.should_continue(
                        plan=adaptive_plan,
                        phase_results=phase_results,
                    ):
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


def cmd_assess(args: argparse.Namespace) -> int:
    """Run a full assessment: recon -> scan -> analyze -> report."""
    target = args.target
    engagement_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    db_path = _apply_local_mode(getattr(args, "local", False), getattr(args, "db", None))

    logger.info("Starting assessment %s against %s", engagement_id[:8], target)
    logger.info("Storage: %s", "in-memory (ephemeral)" if db_path == ":memory:" else db_path)

    _run_startup_health_check()

    # Step 1: Create engagement record
    eng_repo, finding_repo = _setup_local_mode(db_path)
    engagement = eng_repo.create({
        "target_url": target,
        "org_id": "local",
        "status": "created",
        "scan_type": "url",
        "created_by": "cli",
    })
    logger.info("Created engagement %s", engagement.get("id", engagement_id)[:8])

    # Override DATABASE_URL for local execution
    if os.environ.get("ARGUS_LOCAL_MODE", "") != "1":
        os.environ["ARGUS_LOCAL_MODE"] = "1"
    old_db_url = os.environ.pop("DATABASE_URL", None)

    # Create orchestrator
    eng_id = engagement.get("id", engagement_id)
    orch = _get_orchestrator(eng_id, db_path=db_path, trace_id=trace_id)
    orch.engagement_repo = eng_repo
    orch.finding_repo = finding_repo

    # Checkpoint manager for crash recovery
    cp_mgr = None
    if db_path != ":memory:":
        try:
            from database.sqlite_checkpoint import SQLiteCheckpointManager
            cp_mgr = SQLiteCheckpointManager(db_path)
            logger.info("Checkpoints enabled for crash recovery")
        except Exception:
            logger.debug("Checkpoint manager not available", exc_info=True)

    try:
        # Run assessment phases using shared helper
        exit_code, phase_results = _run_phases(
            orch, target,
            engagement_id=eng_id,
            finding_repo=finding_repo,
            aggressiveness=args.aggressiveness or "moderate",
            output_format=args.format or "json",
            phases=("recon", "scan", "analyze", "report"),
            cp_mgr=cp_mgr,
            llm_refine=getattr(args, "llm_refine", False),
            trace_id=trace_id,
        )

        if exit_code != 0:
            return exit_code

        # Output results
        _output_results(eng_id, target, finding_repo, args.output)

        # Clean up checkpoints
        if cp_mgr is not None:
            try:
                cp_mgr.delete_checkpoints(eng_id)
            except Exception:
                logger.debug("Checkpoint cleanup failed", exc_info=True)

        # Store coverage report
        _store_coverage_report(orch, eng_repo, eng_id)

        logger.info("Assessment complete")
        return 0

    finally:
        if old_db_url is not None:
            os.environ["DATABASE_URL"] = old_db_url
        if "ARGUS_LOCAL_MODE" in os.environ:
            del os.environ["ARGUS_LOCAL_MODE"]


def cmd_scan(args: argparse.Namespace) -> int:
    """Run scan phase only."""
    from orchestrator_pkg.orchestrator import Orchestrator

    target = args.target
    engagement_id = str(uuid.uuid4())
    db_path = _apply_local_mode(getattr(args, "local", False), getattr(args, "db", None))

    eng_repo, finding_repo = _setup_local_mode(db_path)
    engagement = eng_repo.create({
        "target_url": target,
        "org_id": "local",
        "status": "scanning",
        "scan_type": "url",
    })

    orch = Orchestrator(engagement_id=engagement.get("id", engagement_id))
    orch.engagement_repo = eng_repo
    orch.finding_repo = finding_repo

    job: dict[str, Any] = {
        "type": "scan",
        "targets": [target],
        "target": target,
        "engagement_id": engagement.get("id", engagement_id),
        "scope": {"mode": "allowlist", "allowed_targets": [target]},
        "aggressiveness": args.aggressiveness or "moderate",
        "agent_mode": False,
    }

    try:
        result = orch.run(job)
        print(json.dumps(result, indent=2, default=str))
        return 0
    except Exception as e:
        logger.error("Scan failed: %s", e)
        return 1


def _display_coverage_report(coverage: dict) -> None:
    """Display a coverage report in a clean table format."""
    sep = "-" * 62
    print("\n  Phase Coverage Report")
    print(f"  {sep}")
    print(f"  {'Phase':<30} {'Status':<15} {'Reason':<25}")
    print(f"  {sep}")

    # Show activated phases
    for name in coverage.get("activated", []):
        print(f"  {name:<30} {'ACTIVE':<15} {'':<25}")

    # Show skipped phases with reasons
    for gap in coverage.get("coverage_gaps", []):
        name = gap.get("name", "unknown")
        reason = gap.get("reason", "")
        # Truncate long reasons
        if len(reason) > 22:
            reason = reason[:19] + "..."
        print(f"  {name:<30} {'SKIPPED':<15} {reason:<25}")

    print(f"  {sep}")
    pct = coverage.get("coverage_pct", 0) * 100
    print(f"  Activated: {coverage.get('activated_count', 0)}/{coverage.get('total_phases', 0)}")
    print(f"  Coverage:  {pct:.0f}%")
    print(f"  Summary:   {coverage.get('summary', '')}")
    print()


def cmd_report(args: argparse.Namespace) -> int:
    """Generate a report from existing findings.

    Supports JSON (default), HTML, Markdown, and PDF output formats.
    Use --coverage to display phase coverage from the adaptive planner.
    """
    from database.sqlite_backend import SQLiteEngagementRepo, SQLiteFindingRepo

    db_path = _apply_local_mode(getattr(args, "local", False), getattr(args, "db", None))
    finding_repo = SQLiteFindingRepo(db_path)
    findings, total = finding_repo.get_findings_by_engagement(
        args.engagement_id, limit=1000
    )
    summary = finding_repo.get_summary_by_engagement(args.engagement_id)

    # ── Coverage report mode ────────────────────────────────────
    if getattr(args, "coverage", False):
        eng_repo = SQLiteEngagementRepo(db_path)
        eng = eng_repo.find_by_id(args.engagement_id)
        if eng and eng.get("metadata"):
            metadata = eng["metadata"]
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except Exception:
                    metadata = {}
            coverage = metadata.get("coverage_report")
            if coverage:
                _display_coverage_report(coverage)
                return 0
            else:
                logger.warning("No coverage report found for engagement %s", args.engagement_id[:8])
                logger.info("Run 'argus assess' first to generate a coverage report.")
                return 1
        else:
            logger.warning("Engagement %s not found", args.engagement_id[:8])
            return 1

    # ── Compliance report mode ────────────────────────────────
    compliance_standard = getattr(args, "compliance", None)
    if compliance_standard:
        try:
            from compliance_reporting import generate_compliance_report
            from reporting.exporter import save_report

            result = generate_compliance_report(
                standard=compliance_standard,
                engagement_id=args.engagement_id,
                findings=findings,
            )

            html = result["html"]
            output = save_report(
                html,
                path=args.output,
                fmt="html",
                target_slug=summary.get("target_url", "") if summary else args.engagement_id,
                open_browser=getattr(args, "open", False),
            )
            logger.info(
                "%s compliance report saved: %s (%d bytes)",
                compliance_standard.upper(), output.path, output.size_bytes,
            )

            # Print JSON summary to stdout unless output is going to a file
            json_data = result["report"]
            if not args.output:
                print(json.dumps(json_data, indent=2, default=str))
            return 0

        except ImportError as e:
            logger.error("Compliance reporting module not available: %s", e)
            logger.info(
                "Install jinja2: 'pip install jinja2' to enable compliance report rendering."
            )
            return 1
        except Exception as e:
            logger.error("Compliance report generation failed: %s", e)
            return 1

    fmt = (args.format or "json").lower()

    if fmt in ("html", "pdf"):
        # Build structured report data for rendering
        severity_breakdown = dict(summary or {}) if summary else None

        if fmt == "html":
            from reporting.html_report import render_html_report

            content = render_html_report(
                title=f"Security Assessment Report — {args.engagement_id[:8]}",
                target=summary.get("target_url", "") if summary else "",
                findings=findings,
                severity_breakdown=severity_breakdown,
                executive_summary=summary.get("executive_summary", "") if summary else "",
            )
        else:  # pdf
            from reporting.pdf_report import render_pdf_report

            content = render_pdf_report(
                title=f"Security Assessment Report — {args.engagement_id[:8]}",
                target=summary.get("target_url", "") if summary else "",
                findings=findings,
                severity_breakdown=severity_breakdown,
                executive_summary=summary.get("executive_summary", "") if summary else "",
            )

        from reporting.exporter import save_report

        result = save_report(
            content,
            path=args.output,
            fmt=fmt,  # type: ignore[arg-type]
            target_slug=summary.get("target_url", "") if summary else args.engagement_id,
            open_browser=getattr(args, "open", False),
        )
        logger.info(
            "%s report saved: %s (%d bytes)",
            fmt.upper(), result.path, result.size_bytes,
        )
    else:
        # Default: JSON or plain text output
        report = {
            "engagement_id": args.engagement_id,
            "generated_at": time.time(),
            "total_findings": total,
            "summary": summary,
            "findings": findings,
        }

        if fmt == "markdown":
            from reporting.exporter import save_report

            md_lines = [
                f"# Security Assessment Report — {args.engagement_id[:8]}",
                "",
                f"**Total findings:** {total}",
                "",
                "## Findings",
                "",
            ]
            for i, f in enumerate(findings, 1):
                sev = (f.get("severity") or "INFO").upper()
                title = f.get("title") or f.get("finding_type") or "Unknown"
                endpoint = f.get("endpoint") or "N/A"
                desc = f.get("description") or ""
                md_lines.append(f"### {i}. [{sev}] {title}")
                md_lines.append(f"**Endpoint:** {endpoint}")
                if desc:
                    md_lines.append(f"**Description:** {desc}")
                md_lines.append("")

            content = "\n".join(md_lines)
            result = save_report(
                content,
                path=args.output,
                fmt="markdown",  # type: ignore[arg-type]
                target_slug=summary.get("target_url", "") if summary else args.engagement_id,
            )
            logger.info(
                "Markdown report saved: %s (%d bytes)",
                result.path, result.size_bytes,
            )
        else:
            # JSON output (default)
            report_json = json.dumps(report, indent=2, default=str)
            if args.output:
                with open(args.output, "w") as f:
                    f.write(report_json)
                logger.info("Report written to %s", args.output)
            else:
                print(report_json)

    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """List recent engagements."""
    from database.sqlite_backend import SQLiteEngagementRepo

    db_path = _apply_local_mode(getattr(args, "local", False), getattr(args, "db", None))
    eng_repo = SQLiteEngagementRepo(db_path)
    engagements = eng_repo.find_by_org("local", limit=args.limit or 20)

    if not engagements:
        print("No engagements found.")
        return 0

    print(f"{'ID':<40} {'Target':<40} {'Status':<15} {'Findings':<10}")
    print("-" * 105)
    for eng in engagements:
        print(
            f"{str(eng.get('id', ''))[:36]:<40} "
            f"{str(eng.get('target', ''))[:38]:<40} "
            f"{str(eng.get('status', '')):<15} "
            f"{str(eng.get('findings_count', '-')):<10}"
        )
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    """Resume a crashed assessment from its last checkpoint.

    Loads the latest checkpoint for an engagement, determines which
    phase to resume from, and runs the remaining phases using the
    shared :func:`_run_phases` helper.

    Usage:
        argus resume <engagement_id> --local
        argus resume <engagement_id> --db assessments.db
    """
    engagement_id = args.engagement_id
    db_path = _apply_local_mode(getattr(args, "local", False), getattr(args, "db", None))

    # Load checkpoint
    try:
        from database.sqlite_checkpoint import SQLiteCheckpointManager
        cp_mgr = SQLiteCheckpointManager(db_path)
    except ImportError as e:
        logger.error("Checkpoint manager not available: %s", e)
        return 1

    plan = cp_mgr.get_resume_plan(engagement_id)
    if plan is None:
        logger.error(
            "No checkpoint found for engagement %s. "
            "Pass --local or --db <path> to locate the database.",
            engagement_id[:8],
        )
        cp_mgr.close()
        return 1

    if not plan.can_resume:
        logger.info("Engagement %s is already complete — nothing to resume", engagement_id[:8])
        cp_mgr.close()
        return 0

    # Load repositories and engagement details
    from database.sqlite_backend import SQLiteEngagementRepo, SQLiteFindingRepo

    eng_repo = SQLiteEngagementRepo(db_path)
    finding_repo = SQLiteFindingRepo(db_path)

    eng = eng_repo.find_by_id(engagement_id)
    if eng is None:
        logger.error("Engagement %s not found", engagement_id[:8])
        cp_mgr.close()
        return 1

    target = eng.get("target_url") or plan.partial_results.get("target", "")
    trace_id = plan.partial_results.get("trace_id", str(uuid.uuid4()))
    aggressiveness = plan.partial_results.get("aggressiveness", "moderate")
    output_format = plan.partial_results.get("format", "json")
    phase_results: list[dict] = plan.partial_results.get("phase_results", [])

    logger.info("Resuming engagement %s from phase '%s'", engagement_id[:8], plan.next_phase)
    logger.info("Remaining phases: %s", ", ".join(plan.remaining_phases))
    logger.info("Last checkpoint: %s", plan.checkpoint_timestamp)

    # Restore ARGUS_LOCAL_MODE
    os.environ["ARGUS_LOCAL_MODE"] = "1"
    old_db_url = os.environ.pop("DATABASE_URL", None)

    # Create orchestrator
    orch = _get_orchestrator(engagement_id, db_path=db_path, trace_id=trace_id)
    orch.engagement_repo = eng_repo
    orch.finding_repo = finding_repo

    try:
        # Run remaining phases using shared helper
        exit_code, phase_results = _run_phases(
            orch, target,
            engagement_id=engagement_id,
            finding_repo=finding_repo,
            aggressiveness=aggressiveness,
            output_format=output_format,
            phases=plan.remaining_phases,
            phase_results=phase_results,
            cp_mgr=cp_mgr,
            llm_refine=getattr(args, "llm_refine", False),
            trace_id=trace_id,
        )

        if exit_code != 0:
            return exit_code

        # Output results
        _output_results(engagement_id, target, finding_repo, args.output)

        # Clean up checkpoints
        try:
            cp_mgr.delete_checkpoints(engagement_id)
        except Exception:
            pass

        # Store coverage report
        _store_coverage_report(orch, eng_repo, engagement_id)

        logger.info("Resume complete")
        return 0

    finally:
        cp_mgr.close()
        if old_db_url is not None:
            os.environ["DATABASE_URL"] = old_db_url
        if "ARGUS_LOCAL_MODE" in os.environ:
            del os.environ["ARGUS_LOCAL_MODE"]


def cmd_trends(args: argparse.Namespace) -> int:
    """Show cross-engagement trend analysis.

    Aggregates findings across all engagements in the SQLite database
    to surface portfolio-level insights: trending vulnerabilities, most
    affected domains, CWE frequency, and risk scoring.

    Usage:
        argus trends
        argus trends --domain example.com
        argus trends --last-n-days 90
        argus trends --min-severity HIGH
        argus trends --verbose
    """
    db_path = _apply_local_mode(getattr(args, "local", False), getattr(args, "db", None))

    try:
        from database.sqlite_trends import SQLiteTrendRepository, display_trend_summary

        repo = SQLiteTrendRepository(db_path)
        trends = repo.get_trends(
            domain=getattr(args, "domain", None),
            last_n_days=getattr(args, "last_n_days", None),
            min_severity=getattr(args, "min_severity", None),
        )

        output = display_trend_summary(
            trends,
            verbose=getattr(args, "verbose", False),
        )
        print(output)
        repo.close()
        return 0

    except ImportError as e:
        logger.error("Trend analysis module not available: %s", e)
        return 1
    except Exception as e:
        logger.error("Trend analysis failed: %s", e)
        return 1


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize Argus configuration: generate encryption keys and .env file.

    Checks for:
    1. Existing .env file (--force to overwrite)
    2. Generates AUTH_CHECKPOINT_KEY (Fernet) if missing
    3. Generates SETTINGS_ENCRYPTION_KEY (Fernet) if missing
    4. Creates local SQLite database directory
    5. Runs preflight check to verify setup

    Returns:
        0 on success, 1 on failure.
    """
    force = getattr(args, "force", False)
    exit_code = 0
    generated: list[str] = []

    # ── Determine .env path ──
    # Walk up from the script directory to find the project root (.env.example location)
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent  # parent of argus-workers/
    env_path = project_root / ".env"

    # Also check if there's an .env in the workers dir
    workers_env = script_dir / ".env"
    env_candidates = [env_path, workers_env]

    # ── Check existing .env ──
    existing_env = None
    for candidate in env_candidates:
        if candidate.exists():
            existing_env = candidate
            break

    if existing_env and not force:
        print(f"  .env already exists at: {existing_env}")
        print(f"  Use --force to overwrite (existing file will be backed up).")
        exit_code = 1
    else:
        # ── Generate encryption keys ──
        try:
            from cryptography.fernet import Fernet

            auth_key = Fernet.generate_key().decode()
            settings_key = Fernet.generate_key().decode()
            generated = ["AUTH_CHECKPOINT_KEY", "SETTINGS_ENCRYPTION_KEY"]

            print(f"  Generated AUTH_CHECKPOINT_KEY:    {auth_key}")
            print(f"  Generated SETTINGS_ENCRYPTION_KEY: {settings_key}")

        except ImportError:
            logger.error("cryptography package not installed — cannot generate Fernet keys")
            print("Error: cryptography package is required. Install with: pip install cryptography")
            return 1

        # ── Write .env ──
        # Use the project root .env path by default
        target_env = env_path

        # Backup existing file if overwriting
        if existing_env:
            backup = existing_env.with_suffix(".env.bak")
            import shutil
            shutil.copy2(existing_env, backup)
            print(f"  Backed up existing .env to: {backup}")
            target_env = existing_env

        try:
            from datetime import datetime

            if existing_env:
                # Read existing content, strip old key lines, add new keys.
                # This preserves ALL other config (DATABASE_URL, LLM_API_KEY, etc.).
                existing_lines = existing_env.read_text(encoding="utf-8").splitlines()
                filtered = [
                    line for line in existing_lines
                    if not line.startswith(("AUTH_CHECKPOINT_KEY=", "SETTINGS_ENCRYPTION_KEY="))
                ]
                # Add header for new keys
                filtered.append("")
                filtered.append(f"# Updated by `argus init` on {datetime.now().isoformat()}")
                filtered.append("# -- Encryption Keys -------------------------------------------")
                filtered.append(f"AUTH_CHECKPOINT_KEY={auth_key}")
                filtered.append(f"SETTINGS_ENCRYPTION_KEY={settings_key}")
                target_env.write_text("\n".join(filtered) + "\n", encoding="utf-8")
            else:
                # No existing .env — create a fresh one
                with open(target_env, "w", encoding="utf-8") as f:
                    f.write("# Argus Environment Configuration (auto-generated by `argus init`)\n")
                    f.write(f"# Generated: {datetime.now().isoformat()}\n")
                    f.write("# ---------------------------------------------------------------\n\n")
                    f.write("# -- Encryption Keys -------------------------------------------\n")
                    f.write(f"AUTH_CHECKPOINT_KEY={auth_key}\n")
                    f.write(f"SETTINGS_ENCRYPTION_KEY={settings_key}\n")

            print(f"  Wrote config to: {target_env}")

            # Load the new env vars into the current process
            os.environ["AUTH_CHECKPOINT_KEY"] = auth_key
            os.environ["SETTINGS_ENCRYPTION_KEY"] = settings_key

        except OSError as e:
            logger.error("Failed to write .env file: %s", e)
            print(f"Error: Could not write .env file: {e}")
            return 1

    # ── Create local SQLite database directory ──
    db_dir = Path.home() / ".argus" / "assessments"
    try:
        db_dir.mkdir(parents=True, exist_ok=True)
        print(f"  Local database directory: {db_dir}")
    except OSError as e:
        logger.warning("Could not create database directory: %s", e)
        print(f"  Warning: Could not create {db_dir}: {e}")

    # ── Run preflight check ──
    print()
    try:
        from runtime.preflight import run_preflight, display_preflight_report

        preflight = run_preflight()
        print(display_preflight_report(preflight, verbose=True))

        if preflight.has_errors():
            print("  Some preflight checks failed. Review the issues above.")
            exit_code = 1
        elif preflight.has_warnings():
            print("  All checks passed with warnings. Review the issues above.")
        else:
            print("  All checks passed!")
    except ImportError as e:
        logger.debug("Preflight module not available: %s", e)
        print("  (Preflight check module not available — skipping)")
    except Exception as e:
        logger.warning("Preflight check failed: %s", e)
        print(f"  (Preflight check failed: {e})")

    # ── Summary ──
    print()
    if generated:
        print(f"  [OK] Generated and saved: {', '.join(generated)}")
        print(f"  [INFO] Restart any running workers to pick up the new keys.")
    if exit_code == 0:
        print("  [OK] Init complete.")
    else:
        print(f"  [WARN] Init completed with issues.")

    return exit_code


def cmd_health(args: argparse.Namespace) -> int:
    """Check and display tool health status and configuration health.

    Runs two sets of checks:
    1. Tool health — probes all registered tool binaries on PATH for
       availability and responsiveness to version probes.
    2. Configuration health — checks environment variables, encryption keys,
       scope config, DNS, LLM config, and database URL.

    Displays both reports as tables, grouped by status.
    """
    verbose = getattr(args, "verbose", False)
    timeout = getattr(args, "timeout", None)
    exit_code = 0

    # ── Section 1: Preflight configuration checks ──
    try:
        from runtime.preflight import run_preflight, display_preflight_report

        preflight = run_preflight()
        print(display_preflight_report(preflight, verbose=verbose))

        if preflight.has_errors():
            exit_code = 1
        if preflight.has_warnings():
            # Warnings alone don't trigger non-zero exit
            pass
    except ImportError as e:
        logger.debug("Preflight module not available: %s", e)
    except Exception as e:
        logger.warning("Preflight check failed: %s", e)

    # ── Section 2: Tool health check ──
    try:
        from tool_core.health_checker import (
            ToolHealthChecker,
            display_health_report,
        )

        checker = ToolHealthChecker(probe_timeout=timeout)

        # Get tool names once, pass to check_all to avoid double-loading
        tool_names = checker._get_all_tool_names()
        logger.info("Probing %d tools (timeout=%ds, verbose=%s)...",
                     len(tool_names),
                     timeout or checker.PROBE_TIMEOUT,
                     verbose)

        report = checker.check_all(tool_names=tool_names)
        output = display_health_report(report, verbose=verbose)
        print(output)

        # Warn if critical tools are unavailable
        critical_missing = [
            r.name for r in report.unavailable
            if r.name in ("nuclei", "httpx", "nmap", "subfinder")
        ]
        if critical_missing:
            logger.warning(
                "Critical tools missing from PATH: %s. "
                "Install them for full assessment capability.",
                ", ".join(critical_missing),
            )

        # Exit with non-zero if any tools are degraded or unavailable
        if report.unavailable_count > 0 or report.degraded_count > 0:
            exit_code = 1

    except ImportError as e:
        logger.error("Tool health check module not available: %s", e)
        print(f"Error: Could not load health checker: {e}")
        print("Run 'pip install -r requirements.txt' first.")
        if exit_code == 0:
            exit_code = 1
    except Exception as e:
        logger.error("Tool health check failed: %s", e)
        print(f"Error: Health check failed: {e}")
        if exit_code == 0:
            exit_code = 1

    return exit_code


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


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="argus",
        description="Argus — autonomous security assessment platform",
        epilog="Run 'argus <command> --help' for command-specific help.",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # argus assess
    assess_parser = subparsers.add_parser(
        "assess", help="Run a full assessment (recon -> scan -> analyze -> report)"
    )
    assess_parser.add_argument("target", help="Target URL to assess")
    assess_parser.add_argument(
        "--aggressiveness", "-a",
        choices=["light", "moderate", "aggressive"],
        default="moderate",
        help="Scan aggressiveness level (default: moderate)",
    )
    # CLI always runs in local/SQLite mode — no Docker/Postgres needed.
    # The --local flag is implicit; remove DATABASE_URL to force offline mode.
    assess_parser.add_argument(
        "--local", action="store_true",
        help="Run in standalone mode (no Docker/Postgres/Redis required; uses SQLite)",
    )
    assess_parser.add_argument(
        "--db", "-d",
        default=None,
        help="SQLite database path (default: in-memory, ephemeral; with --local: ~/.argus/assessments/assessments.db)",
    )
    assess_parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output results to file (JSON)",
    )
    assess_parser.add_argument(
        "--format", "-f",
        choices=["json", "markdown"],
        default="json",
        help="Output format (default: json)",
    )
    assess_parser.add_argument(
        "--llm-refine", action="store_true",
        help="Enable LLM-driven replanning between phases (requires LLM API key)",
    )

    # argus scan
    scan_parser = subparsers.add_parser(
        "scan", help="Run scan phase only"
    )
    scan_parser.add_argument("target", help="Target URL to scan")
    scan_parser.add_argument(
        "--aggressiveness", "-a",
        choices=["light", "moderate", "aggressive"],
        default="moderate",
    )
    scan_parser.add_argument(
        "--local", action="store_true",
        help="Run in standalone mode (no Docker/Postgres/Redis required; uses SQLite)",
    )
    scan_parser.add_argument(
        "--db", "-d", default=None,
        help="SQLite database path",
    )

    # argus report
    report_parser = subparsers.add_parser(
        "report", help="Generate a report from existing findings"
    )
    report_parser.add_argument(
        "engagement_id", help="Engagement UUID"
    )
    report_parser.add_argument(
        "--output", "-o", default=None,
        help="Output file path",
    )
    report_parser.add_argument(
        "--format", "-f",
        choices=["json", "html", "pdf", "markdown"],
        default="json",
        help="Report format (default: json)",
    )
    report_parser.add_argument(
        "--open", action="store_true",
        help="Open HTML report in browser after saving (HTML only)",
    )
    report_parser.add_argument(
        "--coverage", action="store_true",
        help="Show phase coverage report (planned vs executed phases)",
    )
    report_parser.add_argument(
        "--compliance", type=str, default=None,
        choices=["owasp_top10", "pci_dss", "soc2", "nist_csf", "hipaa", "iso_27001"],
        help="Generate a compliance-specific report (owasp_top10, pci_dss, soc2, nist_csf, hipaa, iso_27001)",
    )
    report_parser.add_argument(
        "--local", action="store_true",
        help="Use SQLite from local mode (reads from ~/.argus/assessments/assessments.db)",
    )
    report_parser.add_argument(
        "--db", "-d", default=None,
        help="SQLite database path",
    )

    # argus list
    list_parser = subparsers.add_parser(
        "list", help="List recent engagements"
    )
    list_parser.add_argument(
        "--limit", "-n", type=int, default=20,
        help="Max engagements to show (default: 20)",
    )
    list_parser.add_argument(
        "--local", action="store_true",
        help="List engagements from local SQLite database (~/.argus/assessments/assessments.db)",
    )
    list_parser.add_argument(
        "--db", "-d", default=None,
        help="SQLite database path",
    )

    # argus init
    init_parser = subparsers.add_parser(
        "init", help="Initialize Argus configuration (generate keys, create .env, run preflight)"
    )
    init_parser.add_argument(
        "--force", "-f", action="store_true",
        help="Overwrite existing .env file (creates backup)",
    )

    # argus health
    health_parser = subparsers.add_parser(
        "health", help="Check tool health and display status"
    )
    health_parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show all tools including healthy ones (default: only degraded/unavailable)",
    )
    health_parser.add_argument(
        "--timeout", "-t", type=int, default=None,
        help="Probe timeout in seconds per tool (default: 10)",
    )

    # argus resume
    resume_parser = subparsers.add_parser(
        "resume", help="Resume a crashed assessment from its last checkpoint"
    )
    resume_parser.add_argument(
        "engagement_id", help="Engagement UUID to resume"
    )
    resume_parser.add_argument(
        "--local", action="store_true",
        help="Resume from local SQLite database (~/.argus/assessments/assessments.db)",
    )
    resume_parser.add_argument(
        "--db", "-d", default=None,
        help="SQLite database path",
    )
    resume_parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output results to file (JSON)",
    )
    resume_parser.add_argument(
        "--llm-refine", action="store_true",
        help="Enable LLM-driven replanning between phases (requires LLM API key)",
    )

    # argus trends
    trends_parser = subparsers.add_parser(
        "trends", help="Show cross-engagement trend analysis"
    )
    trends_parser.add_argument(
        "--domain", type=str, default=None,
        help="Filter to engagements matching this domain",
    )
    trends_parser.add_argument(
        "--last-n-days", type=int, default=None,
        help="Only consider engagements from the last N days",
    )
    trends_parser.add_argument(
        "--min-severity", type=str, default=None,
        choices=["CRITICAL", "HIGH", "MEDIUM", "LOW"],
        help="Minimum severity to include (default: all)",
    )
    trends_parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show additional detail (tools, findings over time)",
    )
    trends_parser.add_argument(
        "--local", action="store_true",
        help="Analyze local SQLite database (~/.argus/assessments/assessments.db)",
    )
    trends_parser.add_argument(
        "--db", "-d", default=None,
        help="SQLite database path",
    )

    return parser


def main() -> int:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    # Set default database path (unless --local is used, which manages its own path)
    if not getattr(args, "db", None) and not getattr(args, "local", False):
        # Default: a temp file that persists across commands
        db_dir = Path(tempfile.gettempdir()) / "argus-local"
        db_dir.mkdir(parents=True, exist_ok=True)
        args.db = str(db_dir / "argus.db")

    commands = {
        "assess": cmd_assess,
        "scan": cmd_scan,
        "report": cmd_report,
        "list": cmd_list,
        "health": cmd_health,
        "resume": cmd_resume,
        "trends": cmd_trends,
        "init": cmd_init,
    }

    cmd_fn = commands.get(args.command)
    if cmd_fn:
        return cmd_fn(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
