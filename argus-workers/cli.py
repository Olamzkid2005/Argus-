#!/usr/bin/env python3
"""Argus standalone CLI — run security assessments without Docker/Postgres/Redis.

Usage:
    # Full assessment (recon → scan → analyze → report)
    argus assess https://example.com
    argus assess https://example.com --aggressiveness moderate
    argus assess https://example.com --local --output findings.json

    # Individual phases
    argus scan https://example.com --local
    argus report <engagement_id> --format json

    # List engagements
    argus list

Requires:
    - Python 3.11+
    - Assessment tools (nuclei, httpx, etc.) on PATH for full functionality
    - LLM API key for LLM-powered analysis (optional, degrades gracefully)
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


def cmd_assess(args: argparse.Namespace) -> int:
    """Run a full assessment: recon → scan → analyze → report."""
    target = args.target
    engagement_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    db_path = args.db or ":memory:"

    logger.info("Starting assessment %s against %s", engagement_id[:8], target)
    logger.info("Storage: %s", "in-memory (ephemeral)" if db_path == ":memory:" else db_path)

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

    # Override DATABASE_URL to None for synchronous local execution
    # This forces the pipeline to run without Celery dispatch
    os.environ["ARGUS_LOCAL_MODE"] = "1"
    old_db_url = os.environ.pop("DATABASE_URL", None)

    # Create orchestrator once — persists across all phases so state
    # (adaptive plan, planner instance, recon context) is preserved.
    orch = _get_orchestrator(
        engagement.get("id", engagement_id),
        db_path=db_path,
        trace_id=trace_id,
    )
    orch.engagement_repo = eng_repo
    orch.finding_repo = finding_repo

    # Track phase results for coverage gating
    phase_results: list[dict] = []
    _llm_next_caps: list[str] | None = None
    _llm_refiner_available = False
    try:
        from reporting.llm_refiner import llm_replan_from_findings as _llm_refiner
        _llm_refiner_available = True
    except ImportError:
        pass

    try:
        for phase_name in ("recon", "scan", "analyze", "report"):
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
                "engagement_id": engagement.get("id", engagement_id),
                "scope": {"mode": "allowlist", "allowed_targets": [target]},
                "aggressiveness": args.aggressiveness or "moderate",
                "agent_mode": False,  # Deterministic only (no LLM agent loop)
            }
            if _llm_next_caps:
                job["required_capabilities"] = _llm_next_caps
                _llm_next_caps = None  # Consumed — reset for next phase

            if phase_name == "scan":
                # Recon context is stored on the orchestrator instance from run_recon()
                job["recon_context"] = getattr(orch, "_recon_context", None)
                job["auth_config"] = {}
                job["budget"] = {}

            if phase_name == "analyze":
                job["phase"] = "scan"
                # Findings loaded from repo by SnapshotService — no need to pass

            if phase_name == "report":
                job["format"] = args.format or "json"

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

                # ── LLM refiner: suggest next capabilities ──────────
                # Only run after recon and scan (not after analyze/report)
                if (
                    _llm_refiner_available
                    and getattr(args, "llm_refine", False)
                    and status == "completed"
                    and phase_name in ("recon", "scan")
                ):
                    try:
                        all_findings, _ = finding_repo.get_findings_by_engagement(
                            engagement.get("id", engagement_id), limit=100
                        )
                        refiner_result = _llm_refiner(
                            engagement_id=engagement.get("id", engagement_id),
                            phase=phase_name,
                            target=target,
                            findings=all_findings,
                        )
                        if refiner_result.get("stop", False):
                            logger.info(
                                "LLM refiner suggests stopping: %s",
                                refiner_result.get("reasoning", ""),
                            )
                            # Inject empty caps so next phase runs with default plan
                            _llm_next_caps = []
                        else:
                            _llm_next_caps = refiner_result.get("next_capabilities", [])
                            if _llm_next_caps:
                                logger.info(
                                    "LLM refiner suggests: %s", _llm_next_caps
                                )
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
                    return 1
                # Coverage gate: failed phases count as zero findings
                continue

        # Step 4: Output results
        findings, total = finding_repo.get_findings_by_engagement(
            engagement.get("id", engagement_id), limit=1000
        )
        summary = finding_repo.get_summary_by_engagement(
            engagement.get("id", engagement_id)
        )

        output = {
            "engagement_id": engagement.get("id", engagement_id),
            "target": target,
            "status": "completed",
            "total_findings": total,
            "summary": summary,
            "findings": findings,
        }

        if args.output:
            with open(args.output, "w") as f:
                json.dump(output, f, indent=2, default=str)
            logger.info("Results written to %s", args.output)
        else:
            # Print JSON summary to stdout
            print(json.dumps(output, indent=2, default=str))

        # Step 5: Capture and store coverage report
        try:
            if (
                hasattr(orch, "_adaptive_plan")
                and orch._adaptive_plan is not None
                and hasattr(orch._adaptive_plan, "get_coverage_report")
            ):
                coverage = orch._adaptive_plan.get_coverage_report()
                # Merge with existing engagement metadata (don't overwrite)
                existing_metadata: dict = {}
                try:
                    existing = eng_repo.find_by_id(engagement.get("id", engagement_id))
                    if existing and existing.get("metadata"):
                        raw = existing["metadata"]
                        if isinstance(raw, str):
                            existing_metadata = json.loads(raw)
                        elif isinstance(raw, dict):
                            existing_metadata = raw
                except Exception:
                    pass
                existing_metadata["coverage_report"] = coverage
                eng_repo.update_by_id(
                    engagement.get("id", engagement_id),
                    {"metadata": existing_metadata},
                )
                pct = coverage.get("coverage_pct", 0) * 100
                logger.info(
                    "Phase coverage: %d/%d activated (%.0f%%)",
                    coverage.get("activated_count", 0),
                    coverage.get("total_phases", 0),
                    pct,
                )
        except Exception:
            logger.debug("Could not capture coverage report", exc_info=True)

        logger.info("Assessment complete: %d findings", total)
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
    db_path = args.db or ":memory:"

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

    finding_repo = SQLiteFindingRepo(args.db or ":memory:")
    findings, total = finding_repo.get_findings_by_engagement(
        args.engagement_id, limit=1000
    )
    summary = finding_repo.get_summary_by_engagement(args.engagement_id)

    # ── Coverage report mode ────────────────────────────────────
    if getattr(args, "coverage", False):
        eng_repo = SQLiteEngagementRepo(args.db or ":memory:")
        eng = eng_repo.find_by_id(args.engagement_id)
        if eng and eng.get("metadata"):
            metadata = eng["metadata"]
            if isinstance(metadata, str):
                try:
                    import json
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

    eng_repo = SQLiteEngagementRepo(args.db or ":memory:")
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
        "assess", help="Run a full assessment (recon → scan → analyze → report)"
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
        "--db", "-d",
        default=None,
        help="SQLite database path (default: in-memory, ephemeral)",
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

    # Set default database path
    if not getattr(args, "db", None):
        # Default: a temp file that persists across commands
        db_dir = Path(tempfile.gettempdir()) / "argus-local"
        db_dir.mkdir(parents=True, exist_ok=True)
        args.db = str(db_dir / "argus.db")

    commands = {
        "assess": cmd_assess,
        "scan": cmd_scan,
        "report": cmd_report,
        "list": cmd_list,
    }

    cmd_fn = commands.get(args.command)
    if cmd_fn:
        return cmd_fn(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
