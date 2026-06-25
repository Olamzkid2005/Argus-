"""E2E Smoke Tests — real process-boundary tests against fixture web apps.

These tests start actual Flask processes on random ports, exercising the
process boundary (subprocess invocation, port discovery, health checks,
output parsing, cleanup) that mocks cannot cover.

All tests are marked with @pytest.mark.smoke so they can be excluded
from normal test runs.

Fixture design principle: Make fixtures intentionally tiny, not realistic.
A good fixture is a single vulnerable endpoint in ~30 lines. The purpose
is regression detection, not vulnerability training.

Usage:
    # Run fixture-only tests (no argus CLI needed)
    python -m pytest tests/test_fixture_e2e_smoke.py -m smoke -v --timeout=120 \\
        -k "not scan"

    # Run full suite (requires argus CLI on PATH + flask installed)
    python -m pytest tests/test_fixture_e2e_smoke.py -m smoke -v --timeout=120
"""

import pytest

pytest.importorskip("flask", reason="Flask is required for lifecycle tests")

pytestmark = [
    pytest.mark.smoke,
    pytest.mark.timeout(120),
    pytest.mark.e2e,
]


class TestFixtureAppLifecycle:
    """Tests that start the fixture app directly (no conftest fixtures)."""

    def test_start_app_on_random_port(self):
        """Starting app.py with port 0 binds to a random port."""
        import re
        import subprocess
        import sys
        import time
        import urllib.request

        from tests.conftest import FIXTURE_DIR

        fixture_dir = FIXTURE_DIR / "simple-web-app"
        assert fixture_dir.exists(), f"Fixture dir not found: {fixture_dir}"

        proc = subprocess.Popen(
            [sys.executable, "app.py", "0"],
            cwd=str(fixture_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            deadline = time.monotonic() + 5.0
            port_found = None
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    _, stderr = proc.communicate()
                    pytest.fail(f"Process died early:\n{stderr}")
                line = proc.stderr.readline() if proc.stderr else ""
                match = re.search(r":(\d+)", line)
                if match:
                    port_found = int(match.group(1))
                    break

            assert port_found is not None, "Could not determine port from app output"
            assert 1024 < port_found < 65536, f"Got invalid port: {port_found}"

            health_url = f"http://127.0.0.1:{port_found}/health"
            resp = urllib.request.urlopen(health_url, timeout=5)
            assert resp.status == 200
            assert resp.read().decode() == "ok"

        finally:
            proc.terminate()
            proc.wait(timeout=5)


class TestSimpleWebAppE2E:
    """Smoke tests against the simple-web-app fixture using conftest fixtures."""

    def test_fixture_starts_and_serves_health(self, fixture_app):
        """The fixture app starts and responds to health checks."""
        import urllib.request

        health_url = f"{fixture_app}/health"
        resp = urllib.request.urlopen(health_url, timeout=5)
        assert resp.status == 200
        assert resp.read().decode() == "ok"

    def test_fixture_vulnerable_endpoint_returns_sqli(self, fixture_app):
        """The vulnerable /user endpoint returns an SQL query with user input."""
        import urllib.request

        url = f"{fixture_app}/user?id=1"
        resp = urllib.request.urlopen(url, timeout=5)
        body = resp.read().decode()
        assert "SELECT * FROM users WHERE id=1" in body

    def test_fixture_no_sqli_when_no_param(self, fixture_app):
        """The /user endpoint returns a default query even without id param."""
        import urllib.request

        url = f"{fixture_app}/user"
        resp = urllib.request.urlopen(url, timeout=5)
        body = resp.read().decode()
        assert "SELECT * FROM users" in body

    # ── Scan tests (require argus CLI on PATH + flask installed) ──
    # These tests use run_scan_against_fixture() which calls
    # pytest.skip() if argus CLI is not available, so they safely
    # pass in CI where only the fixture lifecycle is tested.

    def test_scan_returns_dict(self, fixture_app):
        """A scan against the fixture app returns a result dict."""
        from tests.conftest import run_scan_against_fixture

        result = run_scan_against_fixture(fixture_app, timeout=120)
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"

    def test_scan_has_findings_list(self, fixture_app):
        """The scan result contains a list of findings."""
        from tests.conftest import run_scan_against_fixture

        result = run_scan_against_fixture(fixture_app, timeout=120)

        # Scan results should contain findings (possibly empty for some scanner configs)
        findings = result.get("findings", result.get("results", []))
        assert isinstance(findings, list), f"Expected list, got {type(findings)}"


@pytest.mark.parametrize("fixture_app", ["xss-playground"], indirect=True)
class TestXSSPlaygroundE2E:
    """Smoke tests against the xss-playground fixture."""

    def test_fixture_starts_and_serves_health(self, fixture_app):
        """The xss-playground fixture starts and responds to health checks."""
        import urllib.request

        health_url = f"{fixture_app}/health"
        resp = urllib.request.urlopen(health_url, timeout=5)
        assert resp.status == 200
        assert resp.read().decode() == "ok"

    def test_reflected_xss_endpoint(self, fixture_app):
        """The /reflect endpoint echoes unsanitized input in HTML."""
        import urllib.request

        url = f"{fixture_app}/reflect?q=<script>alert(1)</script>"
        resp = urllib.request.urlopen(url, timeout=5)
        body = resp.read().decode()
        assert "<script>alert(1)</script>" in body
        assert "You searched for" in body

    def test_dom_xss_endpoint(self, fixture_app):
        """The /dom endpoint embeds unsanitized input in a script block."""
        import urllib.request

        url = f"{fixture_app}/dom?name=<script>alert('xss')</script>"
        resp = urllib.request.urlopen(url, timeout=5)
        body = resp.read().decode()
        assert "<script>alert('xss')</script>" in body

    def test_stored_xss_post_then_get(self, fixture_app):
        """Stored XSS: POST a comment, GET returns it unsanitized."""
        import urllib.request

        # Post a malicious comment
        post_data = b"comment=<img src=x onerror=alert(1)>"
        post_resp = urllib.request.urlopen(
            f"{fixture_app}/stored", data=post_data, timeout=5
        )
        assert post_resp.status == 201

        # GET the comments page — should include the unsanitized comment
        get_resp = urllib.request.urlopen(f"{fixture_app}/stored", timeout=5)
        body = get_resp.read().decode()
        assert "<img src=x onerror=alert(1)>" in body

    def test_stored_xss_default_no_comments(self, fixture_app):
        """The /stored endpoint shows 'no comments' when empty."""
        import urllib.request

        # Note: this runs in a fresh fixture instance so _stored_comments is empty
        resp = urllib.request.urlopen(f"{fixture_app}/stored", timeout=5)
        body = resp.read().decode()
        assert "No comments yet" in body


@pytest.mark.parametrize("fixture_app", ["auth-bypass"], indirect=True)
class TestAuthBypassE2E:
    """Smoke tests against the auth-bypass fixture."""

    def test_fixture_starts_and_serves_health(self, fixture_app):
        """The auth-bypass fixture starts and responds to health checks."""
        import urllib.request

        health_url = f"{fixture_app}/health"
        resp = urllib.request.urlopen(health_url, timeout=5)
        assert resp.status == 200
        assert resp.read().decode() == "ok"

    def test_login_with_weak_password(self, fixture_app):
        """Login accepts weak passwords (security issue: weak creds)."""
        import urllib.request

        data = b"username=admin&password=password123"
        resp = urllib.request.urlopen(f"{fixture_app}/login", data=data, timeout=5)
        assert resp.status == 200

    def test_login_invalid_returns_401(self, fixture_app):
        """Invalid credentials return 401."""
        import urllib.request

        data = b"username=admin&password=wrongpassword"
        try:
            urllib.request.urlopen(f"{fixture_app}/login", data=data, timeout=5)
            pytest.fail("Expected 401")
        except urllib.error.HTTPError as e:
            assert e.code == 401

    def test_admin_profile_no_auth_required(self, fixture_app):
        """The /admin/profile endpoint is accessible without authentication."""
        import urllib.request

        resp = urllib.request.urlopen(f"{fixture_app}/admin/profile", timeout=5)
        assert resp.status == 200
        import json

        data = json.loads(resp.read().decode())
        assert data["user"] == "anonymous"  # No session but still returns data

    def test_admin_users_exposes_passwords(self, fixture_app):
        """The /admin/users endpoint exposes all credentials."""
        import json
        import urllib.request

        resp = urllib.request.urlopen(f"{fixture_app}/admin/users", timeout=5)
        assert resp.status == 200
        data = json.loads(resp.read().decode())
        users = data.get("users", [])
        assert len(users) >= 3
        passwords = {u.get("password") for u in users}
        assert "password123" in passwords
        assert "welcome1" in passwords

    def test_idor_data_by_id(self, fixture_app):
        """IDOR: user data accessible by ID without ownership check."""
        import json
        import urllib.request

        # Access admin's data record (id=1) without authentication
        resp = urllib.request.urlopen(f"{fixture_app}/api/data/1", timeout=5)
        assert resp.status == 200
        data = json.loads(resp.read().decode())
        assert data["data"]["account"] == "admin"
        assert data["owner"] == "admin"

    def test_flag_endpoint_requires_debug_header(self, fixture_app):
        """The /flag endpoint requires the X-Debug-Token header."""
        import urllib.request

        # Without header — should return 403
        try:
            urllib.request.urlopen(f"{fixture_app}/flag", timeout=5)
            pytest.fail("Expected 403")
        except urllib.error.HTTPError as e:
            assert e.code == 403

    def test_flag_endpoint_bypass_with_header(self, fixture_app):
        """The /flag endpoint can be bypassed with the debug header."""
        import json
        import urllib.request

        req = urllib.request.Request(f"{fixture_app}/flag")
        req.add_header("X-Debug-Token", "argus-bypass-2026")
        resp = urllib.request.urlopen(req, timeout=5)
        assert resp.status == 200
        data = json.loads(resp.read().decode())
        assert "flag" in data
        assert "ARGUS{" in data["flag"]

    def test_idor_record_not_found_returns_error(self, fixture_app):
        """IDOR: requesting a non-existent data ID returns a 404 error."""
        import json
        import urllib.error
        import urllib.request

        try:
            urllib.request.urlopen(f"{fixture_app}/api/data/9999", timeout=5)
            pytest.fail("Expected 404")
        except urllib.error.HTTPError as e:
            assert e.code == 404
            data = json.loads(e.read().decode())
            assert "error" in data
