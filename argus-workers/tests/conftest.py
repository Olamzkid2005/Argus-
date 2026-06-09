"""
Pytest configuration and fixtures
"""
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

logger = logging.getLogger(__name__)

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Add tasks directory for loader imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'tasks')))

# Path to test fixture data directory
FIXTURE_DIR = Path(__file__).resolve().parent.parent / "test_fixtures"


def load_fixture(name: str) -> dict | list:
    """Load a JSON fixture from test_fixtures/ directory.

    Args:
        name: Fixture name without .json extension (e.g., 'sqli_scan').

    Returns:
        Parsed JSON data (dict or list).

    Raises:
        FileNotFoundError: If the fixture file does not exist.
    """
    path = FIXTURE_DIR / f"{name}.json"
    if not path.exists():
        # Check subdirectories
        for subdir in FIXTURE_DIR.iterdir():
            if subdir.is_dir():
                nested = subdir / f"{name}.json"
                if nested.exists():
                    path = nested
                    break
    with open(path) as f:
        return json.load(f)


def get_fixture_path(name: str) -> Path:
    """Get the full path to a fixture file.

    Args:
        name: Fixture name without .json extension (e.g., 'sqli_scan').

    Returns:
        Path to the fixture file.

    Raises:
        FileNotFoundError: If the fixture file does not exist.
    """
    path = FIXTURE_DIR / f"{name}.json"
    if not path.exists():
        # Check subdirectories
        for subdir in FIXTURE_DIR.iterdir():
            if subdir.is_dir():
                nested = subdir / f"{name}.json"
                if nested.exists():
                    return nested
        raise FileNotFoundError(f"Fixture '{name}' not found in {FIXTURE_DIR}")
    return path


# ── E2E Smoke Test Fixtures (Phase 3C) ──────────────────────────────
# These fixtures start real process-boundary services (Flask apps) and
# require the `flask` package to be installed.


def _wait_for_health(url: str, timeout: float = 10.0, interval: float = 0.3) -> bool:
    """Poll a health endpoint until it returns 200 or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = urllib.request.urlopen(url, timeout=2)
            if resp.status == 200:
                return True
        except (urllib.error.URLError, urllib.error.HTTPError, ConnectionError, OSError):
            pass
        time.sleep(interval)
    return False


@pytest.fixture(scope="function")
def fixture_app(request) -> str:
    """Start a fixture web app on a random port and yield its base URL.

    The fixture directory under test_fixtures/ must contain an app.py
    that accepts a port as CLI arg and exposes a /health endpoint.
    The app process is killed when the test finishes.

    Yields:
        Base URL (e.g., "http://127.0.0.1:51234").
    """
    fixture_name = getattr(request, "param", "simple-web-app")
    fixture_dir = FIXTURE_DIR / fixture_name

    if not fixture_dir.exists() or not (fixture_dir / "app.py").exists():
        raise RuntimeError(f"Fixture '{fixture_name}' not found at {fixture_dir}/app.py")

    proc = subprocess.Popen(
        [sys.executable, "app.py", "0"],
        cwd=str(fixture_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Read port from Flask's "Running on http://127.0.0.1:PORT" stderr line
    base_url = None
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            _, stderr = proc.communicate()
            raise RuntimeError(
                f"Fixture '{fixture_name}' exited early (code={proc.returncode}):\n{stderr}"
            )
        line = proc.stderr.readline() if proc.stderr else ""
        match = re.search(r"https?://(\S+)", line)
        if match:
            base_url = match.group(1).rstrip("/")
            break

    if not base_url:
        proc.kill()
        proc.wait(timeout=5)
        raise RuntimeError(f"Could not determine port for fixture '{fixture_name}'")

    health_url = f"http://{base_url}/health"
    if not _wait_for_health(health_url, timeout=10.0):
        proc.kill()
        proc.wait(timeout=5)
        raise RuntimeError(f"Fixture '{fixture_name}' at {health_url} did not become healthy")

    base_url_full = f"http://{base_url}"
    logger.info("Fixture '%s' running at %s", fixture_name, base_url_full)

    yield base_url_full

    # Cleanup
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        logger.warning("Fixture '%s' did not terminate gracefully, killing", fixture_name)
        proc.kill()
        proc.wait(timeout=5)


def run_scan_against_fixture(base_url: str, timeout: int = 120) -> dict:
    """Run an Argus scan against a running fixture and return parsed JSON results.

    Args:
        base_url: The base URL of the target application.
        timeout: Scan timeout in seconds (default: 120).

    Returns:
        Parsed JSON dict with scan results.

    Skips the test if the argus CLI is not found on PATH.
    """
    argus_cli = shutil.which("argus")
    if not argus_cli:
        pytest.skip("argus CLI not found on PATH — skipping smoke test")

    cmd = [argus_cli, "scan", base_url, "--no-cache", "--format", "json"]
    logger.info("Running: %s", " ".join(cmd))

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        pytest.fail(f"argus scan timed out after {timeout}s")

    if result.returncode != 0:
        logger.warning("argus scan stderr:\n%s", result.stderr[:2000])

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        pytest.fail(
            f"Could not parse scan output as JSON.\n"
            f"stdout (first 1000 chars):\n{result.stdout[:1000]}\n"
            f"stderr (first 1000 chars):\n{result.stderr[:1000]}"
        )


# ── Basic test fixtures ──────────────────────────────────────────────


@pytest.fixture
def sample_finding():
    """Sample finding for testing"""
    return {
        "type": "SQL_INJECTION",
        "severity": "HIGH",
        "confidence": 0.8,
        "endpoint": "https://example.com/api",
        "evidence": {
            "payload": "' OR 1=1--",
            "response": "SQL error"
        },
        "source_tool": "nuclei"
    }


@pytest.fixture
def sample_authorized_scope():
    """Sample authorized scope for testing"""
    return {
        "domains": ["staging.app.com", "*.dev.app.com"],
        "ipRanges": ["10.0.0.0/24", "192.168.1.0/24"]
    }


@pytest.fixture
def mock_db_connection_string():
    """Mock database connection string"""
    return "postgresql://test:test@localhost:5432/test_db"
