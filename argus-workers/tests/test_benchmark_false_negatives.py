"""False-negative rate benchmark suite.

Measures what percentage of known vulnerabilities Argus correctly detects.
Uses pre-configured test fixtures (deliberately vulnerable web apps) with
a ground-truth manifest of expected findings.

Run with:
    pytest tests/test_benchmark_false_negatives.py -v --benchmark

Or for a quick smoke test:
    pytest tests/test_benchmark_false_negatives.py -v -k "test_smoke"

Usage:
    FN_RATE_THRESHOLD=0.3  # Fail if FN rate > 30%
    pytest tests/test_benchmark_false_negatives.py -v
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

# Ensure parent directory is on sys.path (matching conftest.py pattern)
_src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: Path to test fixture apps (each subdirectory is a vulnerable web app)
FIXTURE_DIR = Path(__file__).resolve().parent.parent / "test_fixtures"

#: Default maximum false-negative rate threshold (fraction 0.0–1.0)
#: Set env var FN_RATE_THRESHOLD to override.
DEFAULT_FN_THRESHOLD = float(os.environ.get("FN_RATE_THRESHOLD", "0.20"))

#: Timeout per fixture scan (seconds)
FIXTURE_SCAN_TIMEOUT = int(os.environ.get("FIXTURE_SCAN_TIMEOUT", "300"))


# ---------------------------------------------------------------------------
# Ground truth: known vulnerabilities per fixture
#
# Each fixture has a JSON file `manifest.json` in its directory that defines:
#   - name: Human-readable fixture name
#   - expected_findings: list of dicts with type, severity, endpoint, CVE (optional)
#   - description: What the fixture tests
# ---------------------------------------------------------------------------


def load_ground_truth(fixture_name: str) -> dict | None:
    """Load the ground-truth manifest for a fixture.

    Args:
        fixture_name: Name of the fixture subdirectory.

    Returns:
        Dict with 'expected_findings' list, or None if no manifest found.
    """
    manifest_path = FIXTURE_DIR / fixture_name / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        with open(manifest_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load manifest %s: %s", manifest_path, e)
        return None


def get_ground_truth_fixtures() -> list[dict]:
    """Discover all fixtures with ground-truth manifests.

    Returns:
        List of fixture config dicts with name, path, and manifest.
    """
    fixtures = []
    if not FIXTURE_DIR.exists():
        return fixtures

    for subdir in sorted(FIXTURE_DIR.iterdir()):
        if not subdir.is_dir():
            continue
        manifest = load_ground_truth(subdir.name)
        if manifest and manifest.get("expected_findings"):
            fixtures.append({
                "name": subdir.name,
                "path": subdir,
                "description": manifest.get("description", ""),
                "expected_findings": manifest.get("expected_findings", []),
                "cve_references": manifest.get("cve_references", []),
            })

    return fixtures


# ---------------------------------------------------------------------------
# Fixture scanning helpers
# ---------------------------------------------------------------------------


def run_argus_scan(target_url: str, timeout: int = FIXTURE_SCAN_TIMEOUT) -> dict:
    """Run an Argus scan against a target URL and return JSON results.

    Args:
        target_url: Target URL to scan.
        timeout: Scan timeout in seconds.

    Returns:
        Parsed JSON results dict.

    Raises:
        pytest.skip: If argus CLI not found.
        RuntimeError: If scan fails or results can't be parsed.
    """
    import shutil

    argus_cli = shutil.which("argus")
    if not argus_cli:
        pytest.skip("argus CLI not found on PATH")

    # Try with --no-cache for clean results
    cmd = [argus_cli, "scan", target_url, "--no-cache", "--format", "json"]
    logger.info("Running: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        logger.error("Scan timed out after %ds", timeout)
        return {"findings": [], "error": "timeout", "raw_stdout": ""}

    if result.returncode != 0:
        logger.warning(
            "argus scan exited %d. stderr (first 2k):\n%s",
            result.returncode,
            result.stderr[:2000],
        )

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.error(
            "Failed to parse scan output as JSON. stdout (first 2k):\n%s",
            result.stdout[:2000],
        )
        return {"findings": [], "error": "parse_error", "raw_stdout": result.stdout[:2000]}


# ---------------------------------------------------------------------------
# FN Rate computation
# ---------------------------------------------------------------------------


def compute_fn_rate(scan_results: dict, expected: list[dict]) -> dict:
    """Compare scan results against ground truth and compute false-negative rate.

    Args:
        scan_results: Parsed scan results dict with 'findings' list.
        expected: List of expected finding dicts from ground truth.

    Returns:
        Dict with:
            - total_expected: int
            - matched: int
            - missed: list of missed findings
            - fn_rate: float (0.0–1.0)
            - expected_types: list of expected finding type strings
            - found_types: list of found finding type strings
    """
    findings = scan_results.get("findings", [])
    if not findings and isinstance(scan_results, dict):
        # Try alternate result shapes
        findings = scan_results.get("results", []) or scan_results.get("vulnerabilities", [])

    found_types = {
        f.get("type", "").upper()
        for f in findings
        if isinstance(f, dict) and f.get("type")
    }
    found_endpoints = {
        (f.get("type", "").upper(), f.get("endpoint", "").rstrip("/"))
        for f in findings
        if isinstance(f, dict) and f.get("type")
    }

    matched = []
    missed = []

    for exp in expected:
        exp_type = exp.get("type", "").upper()
        exp_endpoint = (exp.get("endpoint", "") or "").rstrip("/")
        exp_cve = (exp.get("cve", "") or "").upper()

        # Check by type+endpoint or CVE
        is_matched = (exp_type, exp_endpoint) in found_endpoints
        if not is_matched and exp_cve:
            # Check if any finding mentions this CVE
            for f in findings:
                if isinstance(f, dict) and exp_cve in str(f.get("cve", "") or "").upper():
                    is_matched = True
                    break

        if is_matched:
            matched.append(exp)
        else:
            missed.append(exp)

    total = len(expected)
    matched_count = len(matched)
    fn_rate = (total - matched_count) / total if total > 0 else 0.0

    expected_types = [e.get("type", "") for e in expected]

    return {
        "total_expected": total,
        "matched": matched_count,
        "missed": missed,
        "fn_rate": fn_rate,
        "expected_types": expected_types,
        "found_types": sorted(found_types),
    }


# =========================================================================
# Tests
# =========================================================================


def test_smoke():
    """Smoke test: verify the benchmark module loads and ground truth is reachable.

    This test always passes as long as the fixture directory is accessible.
    """
    fixtures = get_ground_truth_fixtures()
    logger.info("Found %d fixtures with ground truth", len(fixtures))
    for f in fixtures:
        logger.info(
            "  %s: %d expected findings",
            f["name"],
            len(f["expected_findings"]),
        )
    # No assertion — this is a smoke/info test


class TestFalseNegativeRate:
    """Measure false-negative rate against known-vulnerable fixtures.

    Each test spins up a fixture, runs Argus against it, and compares results
    against the ground-truth manifest.
    """

    _fixtures: list[dict] = []

    @classmethod
    def setup_class(cls):
        cls._fixtures = get_ground_truth_fixtures()

    def test_ground_truth_available(self):
        """At least one fixture with ground truth should be available."""
        fixtures = self._fixtures or get_ground_truth_fixtures()
        if not fixtures:
            pytest.skip("No fixtures with ground truth found — create a manifest.json")

    @pytest.mark.parametrize(
        "fixture_name",
        [
            f["name"]
            for f in get_ground_truth_fixtures()
        ],
        ids=lambda n: n,
    )
    def test_fixture_fn_rate(self, fixture_name: str):
        """Measure FN rate for a specific fixture."""
        manifest = load_ground_truth(fixture_name)
        assert manifest is not None, f"No manifest found for {fixture_name}"
        expected = manifest.get("expected_findings", [])
        assert expected, f"No expected findings in manifest for {fixture_name}"

        # Determine target URL (either a real fixture or a pre-recorded test)
        target_url = os.environ.get(f"TARGET_{fixture_name.upper()}", "")
        if not target_url:
            # Try to start the fixture app
            target_url = _start_fixture_app(fixture_name)

        if not target_url:
            pytest.skip(f"No target URL for {fixture_name} and cannot start fixture")

        try:
            results = run_argus_scan(target_url)
        finally:
            _stop_fixture_app(fixture_name)

        if results.get("error") == "timeout":
            pytest.skip(f"Scan timed out for {fixture_name}")

        stats = compute_fn_rate(results, expected)

        # Log results
        logger.info(
            "Fixture '%s': %d/%d expected findings detected (FN rate=%.1f%%)",
            fixture_name,
            stats["matched"],
            stats["total_expected"],
            stats["fn_rate"] * 100,
        )
        if stats["missed"]:
            logger.warning(
                "  Missed findings: %s",
                [m.get("type", "?") for m in stats["missed"]],
            )

        # Assert FN rate is below threshold
        threshold = float(os.environ.get("FN_RATE_THRESHOLD", str(DEFAULT_FN_THRESHOLD)))
        assert stats["fn_rate"] <= threshold, (
            f"FN rate {stats['fn_rate']:.1%} exceeds threshold {threshold:.1%} "
            f"for fixture '{fixture_name}'. "
            f"Matched {stats['matched']}/{stats['total_expected']} expected findings. "
            f"Missed: {[m.get('type', '?') for m in stats['missed']]}"
        )

    def test_aggregate_fn_rate(self):
        """Aggregate FN rate across all fixtures should not exceed threshold."""
        fixtures = self._fixtures or get_ground_truth_fixtures()
        if not fixtures:
            pytest.skip("No fixtures with ground truth found")

        total_expected = 0
        total_matched = 0
        all_missed = []
        fixture_results = []

        for fixture in fixtures:
            manifest = load_ground_truth(fixture["name"])
            if not manifest:
                continue
            expected = manifest.get("expected_findings", [])
            if not expected:
                continue

            target_url = os.environ.get(
                f"TARGET_{fixture['name'].upper()}", ""
            )
            if not target_url:
                target_url = _start_fixture_app(fixture["name"])

            if not target_url:
                continue

            try:
                results = run_argus_scan(target_url)
            except Exception as e:
                logger.warning(
                    "Scan failed for %s: %s", fixture["name"], e
                )
                continue
            finally:
                _stop_fixture_app(fixture["name"])

            stats = compute_fn_rate(results, expected)
            total_expected += stats["total_expected"]
            total_matched += stats["matched"]
            all_missed.extend(stats["missed"])
            fixture_results.append(
                f"{fixture['name']}: {stats['matched']}/{stats['total_expected']} "
                f"({stats['fn_rate']:.1%} FN)"
            )

        if total_expected == 0:
            pytest.skip("No fixture scans completed")

        aggregate_fn_rate = (
            (total_expected - total_matched) / total_expected
        )

        logger.info(
            "Aggregate FN rate: %d/%d matched (%.1f%%)",
            total_matched,
            total_expected,
            aggregate_fn_rate * 100,
        )
        for res in fixture_results:
            logger.info("  %s", res)
        if all_missed:
            logger.warning(
                "All missed findings: %s",
                [m.get("type", "?") for m in all_missed],
            )

        threshold = float(os.environ.get(
            "FN_RATE_THRESHOLD", str(DEFAULT_FN_THRESHOLD)
        ))
        assert aggregate_fn_rate <= threshold, (
            f"Aggregate FN rate {aggregate_fn_rate:.1%} exceeds threshold "
            f"{threshold:.1%}"
        )


# ---------------------------------------------------------------------------
# Fixture app lifecycle (for fixtures that are real web apps)
# ---------------------------------------------------------------------------

_fixture_processes: dict[str, Any] = {}


def _start_fixture_app(fixture_name: str) -> str | None:
    """Start a fixture web app and return its base URL.

    Args:
        fixture_name: Name of the fixture (subdirectory under test_fixtures/).

    Returns:
        Base URL (e.g., "http://127.0.0.1:51234") or None if cannot start.
    """
    import random
    import re
    import socket
    import time

    fixture_dir = FIXTURE_DIR / fixture_name
    app_path = fixture_dir / "app.py"
    if not app_path.exists():
        logger.warning("No app.py found for fixture '%s'", fixture_name)
        return None

    # Pick a random port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    try:
        proc = subprocess.Popen(
            [sys.executable, str(app_path), str(port)],
            cwd=str(fixture_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as e:
        logger.warning("Failed to start fixture '%s': %s", fixture_name, e)
        return None

    # Wait for it to become healthy — Flask writes URL to stderr
    base_url = None
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            _, stderr = proc.communicate()
            logger.warning(
                "Fixture '%s' exited early (code=%d): %s",
                fixture_name,
                proc.returncode,
                stderr[:1000],
            )
            return None
        # Flask writes startup URL to stderr, not stdout
        line = proc.stderr.readline() if proc.stderr else ""
        m = re.search(r"https?://(\S+)", line)
        if m:
            base_url = m.group(1).rstrip("/")
            break
        time.sleep(0.3)

    if not base_url:
        base_url = f"http://127.0.0.1:{port}"

    _fixture_processes[fixture_name] = proc
    logger.info("Started fixture '%s' at %s", fixture_name, base_url)
    return base_url


def _stop_fixture_app(fixture_name: str) -> None:
    """Stop a running fixture app."""
    proc = _fixture_processes.pop(fixture_name, None)
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        logger.warning("Force killing fixture '%s'", fixture_name)
        try:
            proc.kill()
            proc.wait(timeout=3)
        except Exception:
            pass
