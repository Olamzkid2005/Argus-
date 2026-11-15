"""Contract tests for the Stage 7.1 discovery/verification lab.

These are the fixture's own guarantees, not a scanner test: the lab must expose
a discoverable login/home page and API description, two identities with
user-owned resources, a vulnerable ownership check that has a secure twin, a
per-run marker, a reset endpoint and target-side request logging. If any of
these break, a "swarm found nothing" run says nothing about the swarm.
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "test_fixtures" / "auth-bypass"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Lab:
    """A running lab plus one cookie jar per identity."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self._openers: dict[str, urllib.request.OpenerDirector] = {}

    def opener(self, identity: str = "anonymous"):
        if identity not in self._openers:
            jar = http.cookiejar.CookieJar()
            self._openers[identity] = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(jar)
            )
        return self._openers[identity]

    def request(
        self,
        method: str,
        path: str,
        *,
        identity: str = "anonymous",
        body: dict | None = None,
        headers: dict | None = None,
    ) -> tuple[int, str, dict]:
        data = None
        hdrs = dict(headers or {})
        if body is not None:
            data = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
        req = urllib.request.Request(
            f"{self.base_url}{path}", data=data, headers=hdrs, method=method
        )
        try:
            with self.opener(identity).open(req, timeout=10) as response:
                return response.status, response.read().decode(), dict(response.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode(), dict(exc.headers)

    def get(self, path: str, **kwargs):
        return self.request("GET", path, **kwargs)

    def login(self, identity: str, password: str):
        status, _, _ = self.request(
            "POST", "/login", identity=identity, body={"username": identity, "password": password}
        )
        assert status == 200, f"login for {identity} failed with {status}"
        return self

    def reset(self, marker: str | None = None) -> dict:
        status, body, _ = self.request(
            "POST", "/__lab/reset", body={"run_marker": marker} if marker else {}
        )
        assert status == 200, body
        return json.loads(body)


@pytest.fixture(scope="module")
def lab():
    assert FIXTURE_DIR.joinpath("app.py").exists()
    port = _free_port()
    env = dict(os.environ, LAB_TEST_MODE="1", LAB_RUN_MARKER="contract-start")
    proc = subprocess.Popen(
        [sys.executable, "app.py", str(port)],
        cwd=FIXTURE_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"{base}/health", timeout=1) as response:
                    if response.status == 200:
                        break
            except Exception:
                time.sleep(0.1)
        else:
            raise RuntimeError("lab did not start")
        yield Lab(base)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def test_landing_page_is_discoverable(lab: Lab):
    status, html, _ = lab.get("/")
    assert status == 200
    assert 'action="/login"' in html
    assert 'method="post"' in html
    for link in ("/api/docs", "/api/data/10", "/api/data/11", "/admin/profile", "/xss"):
        assert f'href="{link}"' in html, f"landing page does not link {link}"
    assert "https://sentinel.argus.invalid/do-not-scan" in html


def test_api_description_lists_the_resources(lab: Lab):
    status, body, _ = lab.get("/api/docs")
    assert status == 200
    docs = json.loads(body)
    paths = {entry["path"] for entry in docs["endpoints"]}
    assert "/api/data/{id}" in paths
    assert "/api/secure/data/{id}" in paths
    assert {resource["id"] for resource in docs["resources"]} >= {10, 11}
    assert docs["marker"]


def test_login_form_and_identity_checks(lab: Lab):
    status, html, _ = lab.get("/login")
    assert status == 200 and 'action="/login"' in html

    assert lab.get("/api/me")[0] == 401
    lab.login("user1", "welcome1")
    status, body, _ = lab.get("/api/me", identity="user1")
    assert status == 200
    assert json.loads(body)["user"] == "user1"

    status, _, _ = lab.request(
        "POST", "/login", identity="bad", body={"username": "user1", "password": "nope"}
    )
    assert status == 401


def test_vulnerable_ownership_check_and_secure_twin(lab: Lab):
    lab.login("user1", "welcome1").login("user2", "welcome2")

    # Unauthenticated callers cannot reach either endpoint at all.
    assert lab.get("/api/data/11")[0] == 401
    assert lab.get("/api/secure/data/11")[0] == 401

    # user1 can read user2's resource: the vulnerable ownership check.
    status, body, _ = lab.get("/api/data/11", identity="user1")
    assert status == 200
    leaked = json.loads(body)
    assert leaked["owner"] == "user2"
    assert leaked["requested_by"] == "user1"

    # The secure twin refuses the same request and allows the owner.
    assert lab.get("/api/secure/data/11", identity="user1")[0] == 403
    assert lab.get("/api/secure/data/10", identity="user1")[0] == 200
    assert lab.get("/api/secure/data/11", identity="user2")[0] == 200
    assert lab.get("/api/data/9999", identity="user1")[0] == 404


def test_reset_rotates_markers_and_clears_the_request_log(lab: Lab):
    first = lab.reset()
    marker = first["marker"]
    assert marker
    assert set(first["users"]) == {"user1", "user2", "admin"}

    status, body, _ = lab.get("/api/data/10", identity="anon")
    assert status == 401
    lab.login("user1", "welcome1")
    status, body, _ = lab.get("/api/data/10", identity="user1")
    assert status == 200
    assert json.loads(body)["marker"] == marker

    second = lab.reset()
    assert second["marker"] != marker
    assert lab.reset("pinned-marker")["marker"] == "pinned-marker"
    _, log_body, _ = lab.get("/__lab/requests")
    entries = json.loads(log_body)["requests"]
    # The reset request itself is logged after the reset; nothing before it is.
    assert all(entry["path"] == "/__lab/reset" for entry in entries)


def test_target_side_request_log_records_identity_and_status(lab: Lab):
    marker = lab.reset("log-marker")["marker"]
    lab.login("user2", "welcome2")
    lab.get("/api/data/10", identity="user2")
    status, body, _ = lab.get("/__lab/requests")
    assert status == 200
    log = json.loads(body)
    assert log["marker"] == marker
    assert any(
        entry["path"] == "/api/data/10"
        and entry["status"] == 200
        and entry["identity"] == "user2"
        and entry["marker"] == marker
        for entry in log["requests"]
    )


def test_flag_requires_the_debug_header(lab: Lab):
    assert lab.get("/flag")[0] == 403
    assert lab.get("/flag", headers={"X-Debug-Token": "wrong"})[0] == 403
    status, body, _ = lab.get("/flag", headers={"X-Debug-Token": "argus-bypass-2026"})
    assert status == 200
    assert json.loads(body)["flag"] == "ARGUS{XSS_AUTH_BYPASS_2026}"
