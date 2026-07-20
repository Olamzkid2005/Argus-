#!/usr/bin/env python3
"""
Live-fire runner for auth-bypass fixture app
=============================================

Starts the fixture app, tests each vulnerable endpoint, and verifies
that the expected vulnerability response is present. This is a lightweight
alternative to the full Docker-based live-fire runner — no Celery, no
PostgreSQL, no Redis needed.

Usage:
    python scripts/livefire/test-fixture-auth-bypass.py

Exit code: 0 = all endpoint checks pass, 1 = any check fails
"""

import json
import os
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request

FIXTURE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "argus-workers", "test_fixtures", "auth-bypass")
)
PORT = 18765  # Unlikely to conflict
BASE_URL = f"http://127.0.0.1:{PORT}"

passed = 0
failed = 0


def check(name: str, fn):
    """Run a check and count pass/fail."""
    global passed, failed
    try:
        fn()
        passed += 1
        print(f"  [PASS] {name}")
    except Exception as e:
        failed += 1
        print(f"  [FAIL] {name}: {e}")
        traceback.print_exc()


def http_get(path: str, headers: dict | None = None) -> tuple[int, str]:
    """Make an HTTP GET request and return (status_code, body)."""
    req = urllib.request.Request(f"{BASE_URL}{path}", headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def http_post(path: str, data: dict) -> tuple[int, str]:
    """Make an HTTP POST request and return (status_code, body)."""
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(f"{BASE_URL}{path}", data=body)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


# ── Fixture App Lifecycle ─────────────────────────────────────────────


def start_fixture() -> subprocess.Popen:
    """Start the auth-bypass Flask app and return the process handle."""
    proc = subprocess.Popen(
        [sys.executable, "app.py", str(PORT)],
        cwd=FIXTURE_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait for the app to start
    for _ in range(15):
        time.sleep(0.5)
        try:
            status, _ = http_get("/health")
            if status == 200:
                return proc
        except Exception:
            continue
    raise RuntimeError("Fixture app did not start within 7.5 seconds")


def stop_fixture(proc: subprocess.Popen):
    """Stop the fixture app."""
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


# ══════════════════════════════════════════════════════════════════════
# Endpoint Checks
# ══════════════════════════════════════════════════════════════════════


def check_health():
    """Health endpoint should return 200 with 'ok'."""
    status, body = http_get("/health")
    assert status == 200, f"Expected 200, got {status}"
    assert body == "ok", f"Expected 'ok', got {body!r}"


def check_login_valid():
    """Login with valid credentials should return 200."""
    status, body = http_post("/login", {"username": "admin", "password": "password123"})
    assert status == 200, f"Expected 200, got {status}"
    data = json.loads(body)
    assert data.get("status") == "ok", f"Expected ok status, got {data}"


def check_login_invalid():
    """Login with invalid credentials should return 401."""
    status, body = http_post("/login", {"username": "admin", "password": "wrong"})
    assert status == 401, f"Expected 401, got {status}"


def check_admin_profile_no_auth():
    """Admin profile without auth still returns data (no access control = vuln)."""
    status, body = http_get("/admin/profile")
    assert status == 200, f"Expected 200, got {status}"
    data = json.loads(body)
    assert "secret_key" in data, f"Expected secret_key in response: {data}"
    assert data["secret_key"] == "sk-admin-1234567890abcdef", (
        f"Unexpected secret_key: {data['secret_key']}"
    )


def check_admin_users_disclosure():
    """Admin users list exposes credentials without access control."""
    status, body = http_get("/admin/users")
    assert status == 200, f"Expected 200, got {status}"
    data = json.loads(body)
    users = data.get("users", [])
    assert len(users) == 3, f"Expected 3 users, got {len(users)}"
    passwords = {u["username"]: u["password"] for u in users}
    assert passwords.get("admin") == "password123", (
        f"Expected admin password, got {passwords}"
    )


def check_idor():
    """IDOR: user1 can access admin data (ID=1) without ownership check."""
    status, body = http_get("/api/data/1")
    assert status == 200, f"Expected 200, got {status}"
    data = json.loads(body)
    assert data.get("owner") == "admin", f"Expected admin data, got {data}"
    assert data["data"].get("ssn") == "000-00-0000", (
        f"Expected SSN in leaked data: {data}"
    )


def check_idor_user_data():
    """IDOR: any user can access other users' data by iterating IDs."""
    status, body = http_get("/api/data/10")
    assert status == 200, f"Expected 200, got {status}"
    data = json.loads(body)
    assert data.get("owner") == "user1", f"Expected user1 data, got {data}"


def check_flag_no_header():
    """Flag endpoint without debug header should return 403."""
    status, body = http_get("/flag")
    assert status == 403, f"Expected 403, got {status}"


def check_flag_with_header():
    """Flag endpoint with X-Debug-Token should return 200 with flag."""
    status, body = http_get("/flag", {"X-Debug-Token": "argus-bypass-2026"})
    assert status == 200, f"Expected 200, got {status}"
    data = json.loads(body)
    assert data.get("flag") == "ARGUS{XSS_AUTH_BYPASS_2026}", (
        f"Unexpected flag: {data}"
    )


def check_flag_wrong_token():
    """Flag endpoint with wrong debug token should return 403."""
    status, _ = http_get("/flag", {"X-Debug-Token": "wrong-token"})
    assert status == 403, f"Expected 403, got {status}"


# ══════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════


def main():
    print("=" * 62)
    print("  Auth-Bypass Fixture — Live Endpoint Verification")
    print("=" * 62)
    print()

    # Start fixture
    print("[Setup] Starting auth-bypass fixture app...")
    try:
        proc = start_fixture()
        print(f"  [OK]   App running at {BASE_URL}")
    except Exception as e:
        print(f"  [FAIL] Could not start fixture: {e}")
        sys.exit(1)

    print()

    # Run checks
    print("[Checks] Vulnerability endpoint verification")
    check("health endpoint", check_health)
    check("login with valid credentials", check_login_valid)
    check("login with invalid credentials", check_login_invalid)
    check("admin/profile: broken access control", check_admin_profile_no_auth)
    check("admin/users: credential disclosure", check_admin_users_disclosure)
    check("IDOR: access admin data as anonymous", check_idor)
    check("IDOR: access user1 data as anonymous", check_idor_user_data)
    check("flag: 403 without debug header", check_flag_no_header)
    check("flag: 200 with correct debug token", check_flag_with_header)
    check("flag: 403 with wrong debug token", check_flag_wrong_token)

    # Cleanup
    stop_fixture(proc)

    # Summary
    print()
    print("-" * 62)
    total = passed + failed
    print(f"  Results:  {passed} passed, {failed} failed  (of {total})")
    print("-" * 62)
    print()

    if failed > 0:
        print("[FAIL] Some endpoint checks failed — see errors above.")
        sys.exit(1)
    else:
        print("[PASS] All endpoint checks passed — fixture app behaves as expected.")
        print()
        print("  Vulnerabilities confirmed accessible:")
        print("    - Broken Access Control: /admin/profile, /admin/users")
        print("    - Insecure Direct Object Reference: /api/data/<id>")
        print("    - Weak Credentials: /login (predictable passwords)")
        print("    - Auth Bypass: /flag (debug header)")
        print()


if __name__ == "__main__":
    main()
