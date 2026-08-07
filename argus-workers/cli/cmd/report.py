"""Report command for the Argus CLI."""

from __future__ import annotations

import argparse
import json
import logging
import time

import cli._local_mode as local_mode

logger = logging.getLogger("cli.cmd")


def _display_coverage_report(coverage: dict) -> None:
    """Print the adaptive-plan coverage report in a readable format.

    Args:
        coverage: Coverage report dict from AdaptivePlanner.get_coverage_report()
            (coverage_gaps, activated, activated_count, skipped_count,
            total_phases, coverage_pct).
    """
    total = coverage.get("total_phases", 0)
    activated = coverage.get("activated", []) or []
    activated_count = coverage.get("activated_count", len(activated))
    skipped_count = coverage.get("skipped_count", 0)
    pct = coverage.get("coverage_pct", 0.0)
    gaps = coverage.get("coverage_gaps", []) or []

    print("\n  Phase Coverage Report")
    print(f"  {'=' * 54}")
    print(f"  Total phases:   {total}")
    print(f"  Activated:      {activated_count}")
    print(f"  Skipped:        {skipped_count}")
    print(f"  Coverage:       {pct * 100:.0f}%")
    if activated:
        print("\n  Activated phases:")
        for name in activated:
            print(f"    - {name}")
    if gaps:
        print("\n  Coverage gaps (skipped phases):")
        for gap in gaps:
            print(f"    - {gap.get('name', 'unknown')}: {gap.get('reason', '')}")
    print()


def cmd_report(args: argparse.Namespace) -> int:
    """Generate a report from existing findings.

    Supports JSON (default), HTML, Markdown, and PDF output formats.
    Use --coverage to display phase coverage from the adaptive planner.
    """
    from database.sqlite_backend import SQLiteEngagementRepo, SQLiteFindingRepo

    db_path = local_mode._apply_local_mode(getattr(args, "local", False), getattr(args, "db", None))
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




