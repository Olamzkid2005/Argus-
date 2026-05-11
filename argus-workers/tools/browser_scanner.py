"""
Browser-based SPA scanner using Playwright in a subprocess.

Calls _browser_scan_worker.py as a standalone subprocess to avoid
event-loop deadlocks with Celery's thread pool. The worker process
handles all Playwright operations and returns JSON findings on stdout.

Usage:
    from tools.browser_scanner import scan, is_spa_target

    findings = scan("https://example.com")
    if is_spa_target(["React", "Django"]):
        ...
"""
import json
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

SPA_FRAMEWORKS = {"react", "vue", "angular", "next.js", "nuxt", "svelte", "ember", "backbone"}


def scan(target_url: str, tech_stack: list[str] | None = None, timeout: int = 120) -> list[dict]:
    """
    Run browser-based SPA scan against target in a subprocess.

    Args:
        target_url: Target URL to scan
        tech_stack: Detected technology stack (for logging, not used by worker)
        timeout: Subprocess timeout in seconds

    Returns:
        List of finding dicts
    """
    worker = Path(__file__).parent / "_browser_scan_worker.py"
    if not worker.exists():
        logger.warning(f"Browser scan worker not found at {worker}")
        return []

    try:
        # Pass tech_stack as second argument (worker expects argv[1]=target, argv[2]=tech_json)
        subprocess_args = [sys.executable, str(worker), target_url]
        if tech_stack:
            subprocess_args.append(json.dumps(tech_stack))
        result = subprocess.run(
            subprocess_args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        logger.warning(f"Python interpreter not found at {sys.executable}")
        return []
    except subprocess.TimeoutExpired:
        logger.warning(f"Browser scan timed out after {timeout}s for {target_url}")
        return []

    if result.returncode != 0:
        stderr = result.stderr.strip()[:500] if result.stderr else "unknown error"
        logger.warning(f"Browser scan worker failed (exit {result.returncode}): {stderr}")
        return []

    stdout = result.stdout.strip()
    if not stdout:
        logger.debug(f"Browser scan returned empty output for {target_url}")
        return []

    try:
        findings = json.loads(stdout)
        if not isinstance(findings, list):
            logger.warning(f"Browser scan worker returned non-list JSON: {type(findings).__name__}")
            return []
        logger.info(f"Browser scan complete: {len(findings)} findings for {target_url}")
        return findings
    except json.JSONDecodeError as e:
        logger.warning(f"Browser scan worker returned invalid JSON: {e}")
        return []


def is_spa_target(tech_stack: list[str]) -> bool:
    """Check if any detected technology is an SPA framework."""
    tech_lower = {t.lower().replace(".js", "").replace("-", "") for t in tech_stack}
    spa_lower = {f.lower().replace(".js", "").replace("-", "") for f in SPA_FRAMEWORKS}
    return bool(tech_lower & spa_lower)
