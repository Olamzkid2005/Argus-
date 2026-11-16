"""
playwright_bola must skip, not error, when no credentials are configured.

The phase used to record `usage: playwright_bola.py [-h] --target TARGET
[--creds-file CREDS_FILE]` as an error, which reads like a broken scanner and
turned a deliberate omission into a phase failure. No logins means there is
nothing to compare two identities with: the tool says so and exits 0.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "scripts"
    / "playwright_bola.py"
)


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=120,
    )


class TestPlaywrightBolaSkip:
    def test_no_credentials_exits_zero(self):
        proc = _run("--target", "http://example.com")
        assert proc.returncode == 0, proc.stderr
        assert "usage:" not in proc.stdout
        assert "usage:" not in proc.stderr

    def test_no_credentials_reports_skipped_with_reason(self):
        proc = _run("--target", "http://example.com")
        payload = json.loads(proc.stdout.strip().splitlines()[0])
        assert payload["skipped"] is True
        assert payload["tool"] == "playwright-bola"
        assert "no credentials configured" in payload["reason"]
        assert "skipped" in proc.stderr

    def test_partial_credentials_also_skip(self):
        # Only the attacker's login: still not two identities to compare.
        proc = _run(
            "--target", "http://example.com",
            "--attacker-username", "a", "--attacker-password", "p",
        )
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout.strip().splitlines()[0])
        assert payload["skipped"] is True
