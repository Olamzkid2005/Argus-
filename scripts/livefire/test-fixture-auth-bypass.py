#!/usr/bin/env python3
"""Standalone checks for the Stage 7 ownership lab.

Starts the fixture app, verifies its contract with real HTTP sessions, and
prints the expected findings. No Celery, PostgreSQL, Redis or scanner binaries
are needed — this is the lab's own regression check, separate from the full
live-fire harness.

Usage:
    python scripts/livefire/test-fixture-auth-bypass.py
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import socket
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "argus-workers" / "test_fixtures" / "auth-bypass"
MARKER = "fixture-script-marker"

passed = 0
failed = 0


def check(name: str, fn):
    global passed, failed
    try:
        fn()
        passed += 1
        print(f"  [PASS] {name}")
    except Exception as exc:
        failed += 1
        print(f"  [FAIL] {name}: {exc}")
        traceback.print_exc()


class Lab:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self._openers: dict[str, urllib.request.OpenerDirector] = {}

    def opener(self, identity: str):
        if identity not in self._openers:
            self._openers[identity] = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
            )
        return self._openers[identity]

    def request(self, method: str, path: str, *, identity="anonymous", body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        hdrs = dict(headers or {})
        if data is not None:
            hdrs["Content-Type"] = "application/json"
        req = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=hdrs, method=method)
        try:
            with self.opener(identity).open(req, timeout=10) as response:
                return response.status, response.read().decode()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()

    def get(self, path: str, **kwargs):
        return self.request("GET", path, **kwargs)

    def login(self, username: str, password: str) -> None:
        status, body = self.request(
            "POST", "/login", identity=username, body={"username": username, "password": password}
        )
        assert status == 200, body

    def reset(self, marker=MARKER) -> dict:
        status, body = self.request("POST", "/__lab/reset", body={"run_marker": marker})
        assert status == 200, body
        return json.loads(body)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_fixture(port: int) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "app.py", str(port)],
        cwd=FIXTURE_DIR,
        env=dict(os.environ, LAB_TEST_MODE="1", LAB_RUN_MARKER=MARKER),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        time.sleep(0.1)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                if response.status == 200:
                    return proc
        except Exception:
            continue
    raise RuntimeError("fixture app did not start")


def stop_fixture(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def run_checks(lab: Lab) -> None:
    def landing():
        status, html = lab.get("/")
        assert status == 200
        for link in ("/api/docs", "/api/data/10", "/api/data/11", "/xss"):
            assert f'href="{link}"' in html
        assert 'action="/login"' in html
        assert "sentinel.argus.invalid" in html

    def api_docs():
        status, body = lab.get("/api/docs")
        assert status == 200
        docs = json.loads(body)
        assert any(e["path"] == "/api/data/{id}" for e in docs["endpoints"])
        assert docs["marker"] == MARKER

    def login_required():
        assert lab.get("/api/data/10")[0] == 401
        assert lab.get("/api/secure/data/10")[0] == 401
        lab.login("user1", "welcome1")
        assert lab.get("/api/me", identity="user1")[0] == 200

    def idor_vulnerable():
        status, body = lab.get("/api/data/11", identity="user1")
        assert status == 200, body
        data = json.loads(body)
        assert data["owner"] == "user2", data
        assert data["marker"] == MARKER

    def secure_twin():
        assert lab.get("/api/secure/data/11", identity="user1")[0] == 403
        assert lab.get("/api/secure/data/10", identity="user1")[0] == 200

    def admin_profile():
        status, body = lab.get("/admin/profile")
        assert status == 200
        assert json.loads(body)["secret_key"] == "sk-admin-1234567890abcdef"

    def admin_users():
        status, body = lab.get("/admin/users")
        assert status == 200
        users = json.loads(body)["users"]
        assert {u["username"] for u in users} == {"user1", "user2", "admin"}

    def flag_checks():
        assert lab.get("/flag")[0] == 403
        assert lab.get("/flag", headers={"X-Debug-Token": "wrong"})[0] == 403
        status, body = lab.get("/flag", headers={"X-Debug-Token": "argus-bypass-2026"})
        assert status == 200
        assert json.loads(body)["flag"] == "ARGUS{XSS_AUTH_BYPASS_2026}"

    def reset_and_logging():
        rotated = lab.reset("rotated-marker")
        assert rotated["marker"] == "rotated-marker"
        assert "user2" in rotated["users"]
        status, body = lab.get("/api/data/10", identity="user1")
        assert status == 200
        assert json.loads(body)["marker"] == "rotated-marker"
        status, body = lab.get("/__lab/requests")
        assert status == 200
        paths = [entry["path"] for entry in json.loads(body)["requests"]]
        assert "/api/data/10" in paths

    print("[Checks] Discoverable lab contract")
    check("landing page links login, API and sentinel", landing)
    check("API description is discoverable", api_docs)
    check("session identities are required", login_required)
    check("vulnerable ownership check (IDOR)", idor_vulnerable)
    check("secure twin denies non-owner", secure_twin)
    check("admin/profile broken access control", admin_profile)
    check("admin/users credential disclosure", admin_users)
    check("flag debug-header auth bypass", flag_checks)
    check("reset rotates markers and logs target requests", reset_and_logging)


def main() -> None:
    print("=" * 62)
    print("  Argus Ownership Lab — Contract Verification")
    print("=" * 62)
    port = free_port()
    proc = start_fixture(port)
    lab = Lab(f"http://127.0.0.1:{port}")
    print(f"  [OK] Lab running at {lab.base_url}\n")
    try:
        run_checks(lab)
    finally:
        stop_fixture(proc)

    print("\n" + "-" * 62)
    print(f"  Results:  {passed} passed, {failed} failed  (of {passed + failed})")
    print("-" * 62 + "\n")
    if failed:
        print("[FAIL] Some lab checks failed — see errors above.")
        sys.exit(1)
    print("[PASS] Lab behaves as expected.")
    print("  - Ownership: /api/data/<id> leaks, /api/secure/data/<id> denies")
    print("  - Auth: predictable logins and a debug-header bypass")
    print("  - Harness: reset and request logging are available")


if __name__ == "__main__":
    main()
