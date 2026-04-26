"""
orchestrator_patch.py

Drop-in replacements for the orchestrator methods that previously swallowed
tool errors silently.  Copy these into orchestrator.py.

Before (the bug):
    except Exception as e:
        logger.error("Semgrep scan failed: %s", str(e))   # str(e) was "" !
        return []

After (this patch):
    result = runner.run(command)
    if result.status.is_fatal:
        self._record_tool_failure(engagement_id, result)
        return []
"""
from __future__ import annotations

import logging
from typing import Any

from .tool_result import ToolResult, ToolStatus

logger = logging.getLogger(__name__)


# ── Mixin — add to your Orchestrator class ────────────────────────────────────

class ToolErrorMixin:
    """
    Mixin that gives the Orchestrator structured tool-failure handling.

    Assumes `self.db` / `self._update_engagement()` / `self._get_engagement()`
    follow the same pattern already in orchestrator.py.
    """

    # ── Core: record a failure against an engagement ─────────────────────────

    def _record_tool_failure(
        self,
        engagement_id: str,
        result: ToolResult,
        phase: str = "scanning",
    ) -> None:
        """
        Persist a tool failure to the engagement record so it surfaces in
        reports instead of disappearing into the void.
        """
        failure_entry = {
            "tool": result.tool_name,
            "status": result.status.value,
            "phase": phase,
            "error_type": result.error_type,
            "error_message": result.error_message,
            "fix_hint": result.fix_hint,
            "duration_seconds": result.duration_seconds,
            "command": result.command,
            # Full traceback only in debug mode
            "error_detail": result.error_detail,
        }

        logger.error(
            "[engagement=%s] Tool failure recorded | tool=%s status=%s\n"
            "  Error   : %s\n"
            "  Hint    : %s\n"
            "  Command : %s\n"
            "  Detail  : %s",
            engagement_id,
            result.tool_name,
            result.status.value,
            result.error_message,
            result.fix_hint,
            " ".join(result.command) if result.command else "(none)",
            result.error_detail[:500] if result.error_detail else "(none)",
        )

        # Append to the engagement's tool_failures list in the DB
        engagement = self._get_engagement(engagement_id)
        if engagement:
            failures: list[dict] = engagement.get("tool_failures", [])
            failures.append(failure_entry)
            self._update_engagement(engagement_id, {"tool_failures": failures})

    # ── Convenience: check a batch of results and record all failures ─────────

    def _audit_tool_results(
        self,
        engagement_id: str,
        results: list[ToolResult],
        phase: str = "scanning",
    ) -> tuple[list[ToolResult], list[ToolResult]]:
        """
        Split a list of ToolResults into (ok, failed).
        Records every failure against the engagement automatically.

        Returns (ok_results, failed_results).
        """
        ok: list[ToolResult] = []
        failed: list[ToolResult] = []

        for r in results:
            if r.status.is_ok:
                ok.append(r)
            else:
                failed.append(r)
                self._record_tool_failure(engagement_id, r, phase)

        if failed:
            logger.warning(
                "[engagement=%s] %d/%d tools failed in phase '%s': %s",
                engagement_id,
                len(failed),
                len(results),
                phase,
                [r.tool_name for r in failed],
            )

        return ok, failed

    # ── Convenience: build a human-readable scan health summary ──────────────

    def _build_scan_health_summary(
        self, results: list[ToolResult]
    ) -> dict[str, Any]:
        """
        Returns a dict suitable for embedding in the engagement report's
        'scan_health' section.  Clients can render this as a status table.
        """
        total = len(results)
        ok = sum(1 for r in results if r.status.is_ok)
        failed = total - ok

        tools_summary = []
        for r in results:
            entry: dict[str, Any] = {
                "tool": r.tool_name,
                "status": r.status.value,
                "findings": r.findings_count,
                "duration_s": round(r.duration_seconds, 1),
            }
            if not r.status.is_ok:
                entry["error"] = r.error_message
                entry["fix"] = r.fix_hint
            tools_summary.append(entry)

        return {
            "tools_run": total,
            "tools_ok": ok,
            "tools_failed": failed,
            "reliability_pct": round((ok / total * 100) if total else 0, 1),
            "tools": tools_summary,
        }


# ── Patched orchestrator methods ──────────────────────────────────────────────
# Copy these into the relevant spots in orchestrator.py.
# They show the before/after for the three most critical scan methods.

class OrchestratorPatchedMethods:
    """
    Illustrative class — not instantiated.
    Copy the methods below into your Orchestrator class.
    """

    # ── Semgrep repo scan (replaces the silent-failure version) ───────────────

    def _run_semgrep(
        self,
        engagement_id: str,
        repo_path: str,
        configs: list[str],
    ) -> list[dict]:
        """
        Run semgrep and return findings.  All errors are captured and recorded.
        """
        from .tool_runner import ToolRunner

        command = [
            "semgrep",
            "--json",
            "--no-rewrite-rule-ids",
        ]
        for cfg in configs:
            command += ["--config", cfg]
        command.append(repo_path)

        runner = ToolRunner(tool_name="semgrep", target=repo_path)
        result = runner.run(command)

        if result.status.is_fatal:
            self._record_tool_failure(engagement_id, result, phase="repo_scan")
            return []

        if result.status == result.status.NONZERO_EXIT:
            # semgrep exit 1 is handled inside ToolRunner — reaching here means
            # a genuinely unexpected exit code.
            self._record_tool_failure(engagement_id, result, phase="repo_scan")
            return []

        if not result.stdout.strip():
            logger.info(
                "[engagement=%s] semgrep produced no output (no findings or empty repo).",
                engagement_id,
            )
            return []

        return self._parse_semgrep_output(result.stdout)

    # ── Generic web tool runner (nuclei, dalfox, sqlmap, etc.) ───────────────

    def _run_web_tool(
        self,
        engagement_id: str,
        tool_name: str,
        command: list[str],
        target_url: str,
        parser_fn,   # callable(stdout: str) -> list[dict]
    ) -> list[dict]:
        """
        Generic wrapper for web-based scanners.
        """
        from .tool_runner import ToolRunner

        runner = ToolRunner(tool_name=tool_name, target=target_url)
        result = runner.run(command)

        if not result.status.is_ok:
            self._record_tool_failure(engagement_id, result, phase="web_scan")
            return []

        if not result.stdout.strip():
            return []

        try:
            return parser_fn(result.stdout)
        except Exception as parse_exc:  # noqa: BLE001
            logger.error(
                "[engagement=%s][%s] Output parser failed: %s\nRaw stdout (first 500):\n%s",
                engagement_id,
                tool_name,
                parse_exc,
                result.stdout[:500],
            )
            # Record as a soft failure — tool ran, parser broke
            from .tool_result import ToolResult, ToolStatus
            parse_fail = ToolResult(
                tool_name=tool_name,
                command=command,
                target=target_url,
                status=ToolStatus.EXCEPTION,
                error_type=type(parse_exc).__name__,
                error_message=f"Output parser failed: {parse_exc}",
                error_detail=result.stdout[:2000],
                fix_hint=f"Check the {tool_name} output format — it may have changed.",
            )
            parse_fail.mark_finished()
            self._record_tool_failure(engagement_id, parse_fail, phase="web_scan")
            return []

    # ── Report builder addition ───────────────────────────────────────────────

    def _build_report(self, engagement_id: str) -> dict:
        """
        Extends your existing report builder to include scan health.
        Call self._build_scan_health_summary() with the collected results
        and embed the output under report["scan_health"].
        """
        engagement = self._get_engagement(engagement_id)
        report = {
            # ... your existing fields ...
            "findings": engagement.get("findings", []),
            "scan_health": self._build_scan_health_summary(
                engagement.get("_tool_results_cache", [])
            ),
            "tool_failures": engagement.get("tool_failures", []),
        }

        # If all tools failed → make it obvious in the report headline
        health = report["scan_health"]
        if health["tools_failed"] > 0 and health["findings"] == 0:
            report["zero_findings_reason"] = (
                f"{health['tools_failed']} of {health['tools_run']} security tools "
                f"failed to run. Zero findings does NOT mean the target is clean. "
                f"Fix the tool failures listed in scan_health before trusting this result."
            )

        return report
