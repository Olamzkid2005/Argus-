"""
Browser-based SPA scanner using Playwright in a subprocess.

Calls _browser_scan_worker.py as a standalone subprocess to avoid
event-loop deadlocks with Celery's thread pool. The worker process
handles all Playwright operations and returns JSON findings on stdout.

Usage:
    from tools.browser_scanner import BrowserScanner, scan, is_spa_target

    scanner = BrowserScanner()
    result = scanner.execute(ToolContext(target="https://example.com"))
    # result.findings -> list of finding dicts

    # Legacy API (still works):
    findings = scan("https://example.com")
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from tool_core.base import AbstractTool, ToolContext
from tool_core.result import ToolStatus, UnifiedToolResult
from utils.logging_utils import ScanLogger

logger = logging.getLogger(__name__)

_ALLOWED_BROWSER_SCHEMES = frozenset({"http", "https"})

SPA_FRAMEWORKS = {"react", "vue", "angular", "next.js", "nuxt", "svelte", "ember", "backbone"}


class BrowserScanner(AbstractTool):
    """
    Browser-based SPA scanner using Playwright in a subprocess.

    Implements ``AbstractTool`` so it integrates with the standard tool
    lifecycle: timing, error handling, finding emission, and return as
    ``UnifiedToolResult``.

    Calling convention::

        scanner = BrowserScanner()
        result = scanner.execute(ToolContext(target="https://example.com"))
    """

    tool_name: str = "browser_scanner"

    def execute(self, ctx: ToolContext) -> UnifiedToolResult:
        """
        Run browser-based SPA scan against target in a subprocess.

        Args:
            ctx: ToolContext with ``target`` set to the URL to scan.

        Returns:
            UnifiedToolResult with findings populated.
        """
        target_url = ctx.target
        tech_stack = ctx.tech_stack or None
        timeout = ctx.timeout or 120
        engagement_id = ctx.engagement_id or ""

        slog = ScanLogger(self.tool_name, engagement_id=engagement_id)
        slog.tool_start("browser_scan", target=target_url, tech=len(tech_stack) if tech_stack else 0)

        result = UnifiedToolResult(
            tool_name=self.tool_name,
            target=target_url,
        )

        # Validate URL scheme — block file://, ftp://, etc.
        parsed = urlparse(target_url)
        if parsed.scheme not in _ALLOWED_BROWSER_SCHEMES:
            msg = f"Rejected browser scan with scheme '{parsed.scheme}': {target_url}"
            slog.warn(msg)
            logger.warning(msg)
            result.status = ToolStatus.SKIPPED
            result.error_message = msg
            result.mark_finished()
            return result

        worker = Path(__file__).parent / "_browser_scan_worker.py"
        if not worker.exists():
            msg = f"Browser scan worker not found at {worker}"
            slog.warn(msg)
            logger.warning(msg)
            result.status = ToolStatus.NOT_INSTALLED
            result.error_message = msg
            result.mark_finished()
            return result

        try:
            subprocess_args = [sys.executable, str(worker), target_url]
            if tech_stack:
                subprocess_args.append(json.dumps(tech_stack))
            proc_result = subprocess.run(  # noqa: S603
                subprocess_args,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError:
            msg = f"Python interpreter not found at {sys.executable}"
            slog.warn(msg)
            logger.warning(msg)
            result.status = ToolStatus.NOT_INSTALLED
            result.error_message = msg
            result.mark_finished()
            return result
        except subprocess.TimeoutExpired:
            msg = f"Browser scan timed out after {timeout}s"
            slog.warn(msg)
            logger.warning(msg)
            result.status = ToolStatus.TIMEOUT
            result.error_message = msg
            result.mark_finished()
            return result

        if proc_result.returncode != 0:
            stderr = proc_result.stderr.strip()[:500] if proc_result.stderr else "unknown error"
            msg = f"Browser scan worker failed (exit {proc_result.returncode})"
            slog.warn(msg)
            logger.warning(f"{msg}: {stderr}")
            result.status = ToolStatus.NONZERO_EXIT
            result.error_message = msg
            result.stderr = stderr
            result.mark_finished()
            return result

        stdout = proc_result.stdout.strip()
        if not stdout:
            slog.debug("Browser scan returned empty output")
            logger.debug(f"Browser scan returned empty output for {target_url}")
            result.status = ToolStatus.SUCCESS_EMPTY
            result.mark_finished()
            return result

        try:
            findings = json.loads(stdout)
            if not isinstance(findings, list):
                msg = f"Browser scan returned non-list JSON: {type(findings).__name__}"
                slog.warn(msg)
                logger.warning(msg)
                result.mark_finished()
                return result
            result.findings = findings
            result.status = ToolStatus.SUCCESS
            slog.tool_complete("browser_scan", findings=len(findings))
            logger.info(f"Browser scan complete: {len(findings)} findings for {target_url}")
        except json.JSONDecodeError as e:
            msg = f"Browser scan worker returned invalid JSON: {e}"
            slog.warn(msg)
            logger.warning(msg)
            result.status = ToolStatus.NONZERO_EXIT
            result.error_message = msg
            result.stderr = stdout[:1000]

        result.mark_finished()
        return result


# ── Legacy API (backward-compatible wrappers) ──────────────────────────────


def scan(target_url: str, tech_stack: list[str] | None = None, timeout: int = 120) -> list[dict]:
    """
    Run browser-based SPA scan against target in a subprocess.

    Backward-compatible wrapper that creates a ``BrowserScanner`` and
    calls ``execute()``. Existing callers work unchanged.

    Args:
        target_url: Target URL to scan
        tech_stack: Detected technology stack (for logging, not used by worker)
        timeout: Subprocess timeout in seconds

    Returns:
        List of finding dicts
    """
    scanner = BrowserScanner()
    ctx = ToolContext(target=target_url, timeout=timeout)
    if tech_stack:
        ctx.tech_stack = tech_stack
    result = scanner.execute(ctx)
    return result.findings


def is_spa_target(tech_stack: list[str]) -> bool:
    """Check if any detected technology is an SPA framework."""
    tech_lower = {t.lower().replace(".js", "").replace("-", "") for t in tech_stack}
    spa_lower = {f.lower().replace(".js", "").replace("-", "") for f in SPA_FRAMEWORKS}
    return bool(tech_lower & spa_lower)
