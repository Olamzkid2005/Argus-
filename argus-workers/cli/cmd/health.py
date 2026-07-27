"""Health command for the Argus CLI."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import cli._local_mode as local_mode

logger = logging.getLogger("cli.cmd")


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




