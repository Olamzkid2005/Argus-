#!/usr/bin/env python3
"""Turn a live-fire run into a pass/fail verdict, and keep a baseline to diff against.

`run-livefire.sh` collected evidence but asserted nothing: it printed a findings
count and exited 0 whatever happened. `scripts/livefire/README.md` pre-commits
the success criteria, so this script applies them to the run's own artifacts and
database rows and writes `verdict.json` next to them.

Two kinds of criteria, deliberately separated:

* **Absolute** — true of any target: the pipeline reached a terminal state,
  findings were persisted, scope held, no scanner process outlived the run, the
  worker stayed under its memory budget, and recorded tool selections include at
  least one the engine actually chose.
* **Target-relative** — the README's numbers (10-25 findings, >30% of HIGH+
  verified, 11-31 min) describe Juice Shop. For any other target the first run
  records a baseline and later runs must stay within tolerance of it, so a
  regression shows up as a failed criterion instead of a silent drift.

Reads the database as an outsider on purpose: this is a validation tool, so it
does not import the app's connection manager or repositories. Run it with the
worker venv (`argus-workers/venv/bin/python`), which has psycopg2.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import psycopg2
except ImportError:  # pragma: no cover - documented requirement
    print("assert-livefire: psycopg2 is required (use argus-workers/venv)", file=sys.stderr)
    raise

# Binaries a run may spawn. Anything still running after the engagement reached
# a terminal state is an orphan — the README's "Orphan processes: 0 post-scan".
SCANNER_BINARIES = (
    "nuclei", "nmap", "ffuf", "nikto", "sqlmap", "dalfox", "commix", "arjun",
    "subfinder", "httpx", "katana", "gospider", "whatweb", "wpscan", "masscan",
    "dnsx", "naabu", "amass", "testssl.sh", "feroxbuster",
)

# README's "What Good Looks Like", for the target it was written about.
JUICE_SHOP = {
    "label": "juice-shop",
    "min_findings": 10,
    "max_findings": 25,
    "min_high_critical": 2,
    "min_high_verified_fraction": 0.30,
    "min_duration_seconds": 11 * 60,
    "max_duration_seconds": 31 * 60,
}

BASELINE_TOLERANCE = 0.5  # a run may move ±50% off the recorded baseline
WORKER_MEMORY_BUDGET_MB = 500


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assert a live-fire run's criteria")
    parser.add_argument("--run-dir", required=True, help="where the run's artifacts live")
    parser.add_argument("--engagement-id", required=True)
    parser.add_argument("--target-url", default="")
    parser.add_argument("--label", default="target")
    parser.add_argument("--duration-seconds", type=int, default=0)
    parser.add_argument("--worker-rss-mb", type=float, default=None, help="peak RSS, if sampled")
    parser.add_argument("--worker-log", default="", help="worker log to read this run's events from")
    parser.add_argument(
        "--worker-log-start-line", type=int, default=0,
        help="line the worker log stood at when this run started",
    )
    parser.add_argument("--db-url", default=os.getenv("DATABASE_URL", ""))
    parser.add_argument("--baseline-dir", default=str(Path.cwd() / "livefire-runs"))
    return parser.parse_args(argv)


def query(db_url: str, sql: str, params: tuple = ()) -> list[tuple]:
    with psycopg2.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def scalar(db_url: str, sql: str, params: tuple = ()) -> object:
    rows = query(db_url, sql, params)
    return rows[0][0] if rows else None


def orphan_processes() -> list[str]:
    found: list[str] = []
    for binary in SCANNER_BINARIES:
        try:
            out = subprocess.run(
                ["pgrep", "-f", f"(^|/){re.escape(binary)}( |$)"],
                capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return found
        if out.returncode == 0 and out.stdout.strip():
            found.append(binary)
    return found


def worker_log_lines(worker_log: str, start_line: int = 0) -> list[str]:
    """Lines the worker wrote during this run.

    `start_line` is where the log stood when the run began, so a decision made
    from the log is made on this run's lines: the harness re-uses one worker, and
    an earlier run's refusals (that same engagement id, blocked for scope) would
    otherwise be read as this run's.
    """
    path = Path(worker_log) if worker_log else None
    if not path or not path.exists():
        return []
    lines = path.read_text(errors="replace").splitlines()
    return lines[min(start_line, len(lines)):]


def swarm_events(lines: list[str]) -> int:
    return sum(1 for line in lines if "Swarm:" in line)


def engagement_log_lines(lines: list[str], engagement_id: str) -> list[str]:
    """This engagement's pipeline lines.

    They carry the engagement's first eight characters in brackets
    (`[a1b2c3d4]`).
    """
    prefix = engagement_id[:8]
    return [line for line in lines if f"[{prefix}]" in line]


def scope_block_reason(lines: list[str]) -> str | None:
    """The reason the pipeline refused to scan the target, if it did.

    A loopback target is an internal/SSRF target to the worker unless it was
    started with ARGUS_ALLOW_INTERNAL_TARGETS=1. Without that, every phase
    completes cleanly and finds nothing — a run that looks green and proves
    nothing — so it is asserted on rather than left in the logs.
    """
    for line in lines:
        if "unauthorized internal/SSRF target" in line:
            return "target blocked as an internal/SSRF target (start the worker with ARGUS_ALLOW_INTERNAL_TARGETS=1 to scan loopback targets)"
    return None


def add(criteria: list[dict], name: str, passed: bool, expected: str, actual: object, note: str = "") -> None:
    criteria.append(
        {"name": name, "passed": bool(passed), "expected": expected, "actual": actual, "note": note}
    )


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if not args.db_url:
        print("assert-livefire: DATABASE_URL is not set and --db-url was not given", file=sys.stderr)
        return 2

    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    engagement = args.engagement_id

    state = scalar(args.db_url, "SELECT status FROM engagements WHERE id = %s;", (engagement,))
    severity_rows = query(
        args.db_url,
        "SELECT severity, COUNT(*) FROM findings WHERE engagement_id = %s GROUP BY severity;",
        (engagement,),
    )
    by_severity = {str(sev).upper(): int(count) for sev, count in severity_rows}
    total_findings = sum(by_severity.values())
    high_critical = by_severity.get("CRITICAL", 0) + by_severity.get("HIGH", 0)
    high_total = high_critical
    high_verified = 0
    if high_total:
        high_verified = int(
            scalar(
                args.db_url,
                "SELECT COUNT(*) FROM findings WHERE engagement_id = %s AND verified = true "
                "AND upper(severity) IN ('CRITICAL','HIGH');",
                (engagement,),
            )
            or 0
        )
    scope_violations = int(
        scalar(args.db_url, "SELECT COUNT(*) FROM scope_violations WHERE engagement_id = %s;", (engagement,))
        or 0
    )
    decisions_total = int(
        scalar(args.db_url, "SELECT COUNT(*) FROM agent_decisions WHERE engagement_id = %s;", (engagement,))
        or 0
    )
    decisions_engine = int(
        scalar(
            args.db_url,
            "SELECT COUNT(*) FROM agent_decisions WHERE engagement_id = %s AND was_fallback = false;",
            (engagement,),
        )
        or 0
    )
    fallback_rate = 0.0 if not decisions_total else 1 - decisions_engine / decisions_total
    run_log_lines = worker_log_lines(args.worker_log, args.worker_log_start_line)
    for_this_run = engagement_log_lines(run_log_lines, engagement)
    scope_block = scope_block_reason(for_this_run)
    orphans = orphan_processes()
    swarm = swarm_events(run_log_lines)
    verified_fraction = (high_verified / high_total) if high_total else None

    metrics = {
        "engagement_id": engagement,
        "target_url": args.target_url,
        "label": args.label,
        "final_state": state,
        "total_findings": total_findings,
        "findings_by_severity": by_severity,
        "high_critical_total": high_total,
        "high_critical_verified": high_verified,
        "high_verified_fraction": verified_fraction,
        "scope_violations": scope_violations,
        "orphan_processes": orphans,
        "worker_peak_rss_mb": args.worker_rss_mb,
        "decisions_total": decisions_total,
        "decisions_engine_chosen": decisions_engine,
        "fallback_rate": round(fallback_rate, 4),
        "swarm_events": swarm,
        "scope_block": scope_block,
        "duration_seconds": args.duration_seconds,
    }

    criteria: list[dict] = []
    add(criteria, "pipeline_completed", state == "complete", "engagements.status = complete", state)
    add(criteria, "target_scanned", scope_block is None, "target not refused by the scope guard", scope_block or "scanned", scope_block or "")
    add(criteria, "findings_recorded", total_findings > 0, ">= 1 finding persisted", total_findings)
    add(criteria, "no_scope_violations", scope_violations == 0, "0", scope_violations)
    add(criteria, "no_orphan_tool_processes", not orphans, "0", orphans)
    if args.worker_rss_mb is not None:
        add(
            criteria, "worker_memory_within_budget",
            args.worker_rss_mb < WORKER_MEMORY_BUDGET_MB,
            f"< {WORKER_MEMORY_BUDGET_MB} MB", f"{args.worker_rss_mb:.0f} MB",
        )
    add(
        criteria, "agent_selection_recorded", decisions_engine > 0,
        ">= 1 engine-chosen decision", f"{decisions_engine} of {decisions_total}",
        "the run must show the engine choosing tools, not only deterministic fallbacks",
    )
    # Verification is only an absolute criterion for the target the README's
    # numbers describe. Elsewhere it is recorded: a fixture's single HIGH finding
    # can be a protocol observation (no HTTPS) that no HTTP probe can confirm, and
    # failing a run for that would say more about the target than the pipeline.
    if high_total and args.label == JUICE_SHOP["label"]:
        add(
            criteria, "high_findings_verified",
            (verified_fraction or 0) >= JUICE_SHOP["min_high_verified_fraction"],
            f">= {JUICE_SHOP['min_high_verified_fraction']:.0%} of HIGH+ verified",
            f"{(verified_fraction or 0):.0%} ({high_verified}/{high_total})",
        )

    baseline_path = Path(args.baseline_dir) / f"baseline-{args.label}.json"
    baseline = json.loads(baseline_path.read_text()) if baseline_path.exists() else None
    baseline_delta: dict[str, object] = {}
    if baseline is None:
        if args.label == JUICE_SHOP["label"]:
            add(
                criteria, "findings_in_juice_shop_range",
                JUICE_SHOP["min_findings"] <= total_findings <= JUICE_SHOP["max_findings"],
                f"{JUICE_SHOP['min_findings']}-{JUICE_SHOP['max_findings']}", total_findings,
            )
            add(criteria, "high_critical_present", high_critical >= JUICE_SHOP["min_high_critical"],
                f">= {JUICE_SHOP['min_high_critical']}", high_critical)
            add(
                criteria, "duration_in_juice_shop_window",
                JUICE_SHOP["min_duration_seconds"] <= args.duration_seconds <= JUICE_SHOP["max_duration_seconds"],
                f"{JUICE_SHOP['min_duration_seconds']}-{JUICE_SHOP['max_duration_seconds']}s",
                f"{args.duration_seconds}s",
            )
    else:
        # Outcome and resources, not wall-clock: a label's duration depends on
        # which tools the run happened to select, and comparing it made the
        # second run fail against a first run that had scanned nothing.
        for key in ("total_findings", "worker_peak_rss_mb"):
            previous = baseline.get("metrics", {}).get(key)
            current = metrics.get(key)
            if previous in (None, 0) or current is None:
                continue
            delta = (current - previous) / previous
            baseline_delta[key] = {"baseline": previous, "current": current, "delta": round(delta, 3)}
            add(
                criteria, f"baseline_{key}_stable",
                abs(delta) <= BASELINE_TOLERANCE,
                f"within ±{BASELINE_TOLERANCE:.0%} of {previous}",
                f"{current} ({delta:+.0%})",
            )

    passed = all(item["passed"] for item in criteria)
    verdict = {
        "run": {
            "label": args.label,
            "target_url": args.target_url,
            "run_dir": str(run_dir),
            "asserted_at": datetime.now(timezone.utc).isoformat(),
        },
        "passed": passed,
        "criteria": criteria,
        "metrics": metrics,
        "baseline": {"file": str(baseline_path), "existed": baseline is not None, "delta": baseline_delta},
        "pre_committed_by": "scripts/livefire/README.md",
    }
    (run_dir / "verdict.json").write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n")

    # First run for this label becomes the baseline it is later diffed against.
    if baseline is None:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(
            json.dumps(
                {
                    "label": args.label,
                    "created_from_run": str(run_dir),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "metrics": metrics,
                },
                indent=2, sort_keys=True,
            ) + "\n"
        )

    failed = [item for item in criteria if not item["passed"]]
    print(f"verdict: {'PASS' if passed else 'FAIL'} ({len(criteria) - len(failed)}/{len(criteria)} criteria)")
    for item in criteria:
        mark = "ok  " if item["passed"] else "FAIL"
        print(f"  [{mark}] {item['name']}: expected {item['expected']}, got {item['actual']}")
    print(f"  verdict.json: {run_dir / 'verdict.json'}")
    print(f"  baseline:     {baseline_path} ({'updated' if baseline is None else 'compared'})")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
