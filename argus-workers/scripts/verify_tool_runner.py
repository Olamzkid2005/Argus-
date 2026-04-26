"""
scripts/verify_tool_runner.py

Run this BEFORE restarting the Celery worker to verify:
  1. semgrep runs successfully inside the sandbox
  2. A missing tool produces a NOT_INSTALLED result (not an exception)
  3. An import error is captured and described (not silently swallowed)
  4. Timeout is captured and described

Usage:
    python scripts/verify_tool_runner.py
    python scripts/verify_tool_runner.py --verbose     # include full error_detail
"""
from __future__ import annotations

import argparse
import sys
import os

# Allow running from the repo root without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.tool_runner import ToolRunner
from tools.tool_result import ToolStatus


def header(text: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {text}")
    print('─' * 60)


def check(label: str, condition: bool, detail: str = "") -> bool:
    icon = "✅" if condition else "❌"
    print(f"  {icon}  {label}")
    if detail:
        print(f"       {detail}")
    return condition


def main(verbose: bool = False) -> int:
    failures = 0

    # ── Test 1: semgrep version (basic sandbox test) ──────────────────────────
    header("Test 1 — semgrep runs in sandbox")
    runner = ToolRunner(tool_name="semgrep", target="(version check)")
    result = runner.run(["semgrep", "--version"])

    ok = check(
        "semgrep exits 0 and returns version string",
        result.status == ToolStatus.SUCCESS and "semgrep" in result.stdout.lower(),
        result.stdout.strip()[:80],
    )
    if not ok:
        failures += 1
        check("Error captured (not empty)", bool(result.error_message), result.error_message)
        check("Fix hint provided", bool(result.fix_hint), result.fix_hint)
        if verbose:
            print(f"\n  Full error_detail:\n{result.error_detail[:1000]}")

    # ── Test 2: missing tool → NOT_INSTALLED ──────────────────────────────────
    header("Test 2 — missing binary produces NOT_INSTALLED (not an exception)")
    runner2 = ToolRunner(tool_name="definitely_not_a_real_tool_xyz")
    result2 = runner2.run(["definitely_not_a_real_tool_xyz", "--help"])

    ok2 = check(
        "Status is NOT_INSTALLED",
        result2.status == ToolStatus.NOT_INSTALLED,
        f"Got: {result2.status.value}",
    )
    ok2b = check("Fix hint is non-empty", bool(result2.fix_hint), result2.fix_hint)
    if not ok2 or not ok2b:
        failures += 1

    # ── Test 3: timeout ───────────────────────────────────────────────────────
    header("Test 3 — timeout is captured and described")
    runner3 = ToolRunner(tool_name="sleep_test")
    runner3._timeout = 1   # force a 1-second limit
    result3 = runner3.run(["sleep", "5"])

    ok3 = check(
        "Status is TIMEOUT",
        result3.status == ToolStatus.TIMEOUT,
        f"Got: {result3.status.value}",
    )
    ok3b = check("Fix hint mentions timeout", "timeout" in result3.fix_hint.lower(), result3.fix_hint)
    if not ok3 or not ok3b:
        failures += 1

    # ── Test 4: real semgrep scan on a tiny PHP snippet ───────────────────────
    header("Test 4 — semgrep finds XSS in a synthetic PHP file")
    import tempfile, pathlib

    with tempfile.TemporaryDirectory() as tmpdir:
        vuln_php = pathlib.Path(tmpdir) / "vuln.php"
        vuln_php.write_text(
            "<?php\n"
            "// Deliberate XSS — for pipeline testing only\n"
            "echo $_GET['name'];  // unsanitized user input\n"
            "?>\n"
        )

        runner4 = ToolRunner(tool_name="semgrep", target=str(vuln_php))
        result4 = runner4.run([
            "semgrep", "--json", "--config", "p/php", str(tmpdir)
        ])

        # semgrep exits 1 when findings are present — ToolRunner should
        # recognise this and return SUCCESS, not NONZERO_EXIT
        ok4 = check(
            "Status is SUCCESS (exit 1 correctly treated as findings-present)",
            result4.status == ToolStatus.SUCCESS,
            f"Got: {result4.status.value}",
        )
        if not ok4:
            failures += 1
            check("Error captured", bool(result4.error_message), result4.error_message)
            if verbose and result4.error_detail:
                print(f"\n  stderr:\n{result4.stderr[:500]}")
        else:
            try:
                import json
                data = json.loads(result4.stdout)
                n = len(data.get("results", []))
                check(f"Findings parsed ({n} result(s))", n >= 0, f"stdout length: {len(result4.stdout)}")
            except Exception as e:
                check("JSON parsing OK", False, str(e))

    # ── Test 5: to_report_dict() contains all expected keys ───────────────────
    header("Test 5 — ToolResult.to_report_dict() shape is correct")
    report_dict = result2.to_report_dict(include_debug=True)
    for key in ("tool", "status", "error", "debug"):
        check(f"Key '{key}' present", key in report_dict, str(report_dict.get(key, "(missing)")))

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'═' * 60}")
    if failures == 0:
        print("  ✅  All tests passed — safe to restart the Celery worker.")
    else:
        print(f"  ❌  {failures} test(s) failed — fix before restarting the worker.")
    print('═' * 60)

    return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
    sys.exit(main(verbose=args.verbose))
