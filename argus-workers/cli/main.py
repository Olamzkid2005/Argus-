"""Argus CLI — main entry point and argument parser."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

from cli.cmd import (
    assess,
    scan,
    report,
    list as list_cmd,
    health,
    resume,
    trends,
    verify,
    init,
)

logger = logging.getLogger("cli")

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

    # argus verify
    verify_parser = subparsers.add_parser(
        "verify", help="Re-verify findings and produce remediation diff report"
    )
    verify_parser.add_argument(
        "engagement_id", help="Engagement UUID to verify"
    )
    verify_parser.add_argument(
        "--output", "-o", default=None,
        help="Output verification report to file (JSON)",
    )
    verify_parser.add_argument(
        "--local", action="store_true",
        help="Use SQLite from local mode (reads from ~/.argus/assessments/assessments.db)",
    )
    verify_parser.add_argument(
        "--db", "-d", default=None,
        help="SQLite database path",
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
        "assess": assess.cmd_assess,
        "scan": scan.cmd_scan,
        "report": report.cmd_report,
        "list": list_cmd.cmd_list,
        "health": health.cmd_health,
        "resume": resume.cmd_resume,
        "trends": trends.cmd_trends,
        "verify": verify.cmd_verify,
        "init": init.cmd_init,
    }

    cmd_fn = commands.get(args.command)
    if cmd_fn:
        return cmd_fn(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
