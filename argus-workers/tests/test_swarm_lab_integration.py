"""Stage 7.3: real specialist bodies against the resettable lab.

The recon signals are produced by crawling the running lab (landing page and
API description), not hand-written here. The tool double performs real HTTP
against the lab and records what the specialists executed, so the routing,
scope filter and evidence path are exercised end to end. Scanner binaries are
not installed in this environment; the live-fire harness is what requires them.
"""

from __future__ import annotations

import http.cookiejar
import json
import logging
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.swarm import APIAgent, AuthAgent, IDORAgent, SwarmOrchestrator
from models.recon_context import ReconContext

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "test_fixtures" / "auth-bypass"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def lab():
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "app.py", str(port)],
        cwd=FIXTURE_DIR,
        env=dict(os.environ, LAB_TEST_MODE="1", LAB_RUN_MARKER="integration"),
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
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def _post_marker(base: str) -> str:
    request = urllib.request.Request(
        f"{base}/__lab/reset",
        data=json.dumps({"run_marker": "swarm-lab"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read())["marker"]


def discover(base: str) -> ReconContext:
    """Build the context from what the lab actually exposes."""
    with urllib.request.urlopen(f"{base}/", timeout=5) as response:
        html = response.read().decode()
    links = {
        link if link.startswith("http") else f"{base}{link}"
        for link in re.findall(r'href="([^"]+)"', html)
        if link.startswith("/")
    }
    with urllib.request.urlopen(f"{base}/api/docs", timeout=5) as response:
        docs = json.loads(response.read())

    api_paths = [
        # The secure twin is probed with the other user's id, so the secure
        # control is exercised with the same request that leaks on /api/data.
        f"{base}{entry['path'].replace('{id}', '11' if 'secure' in entry['path'] else '10')}"
        for entry in docs["endpoints"]
        if entry["path"].startswith("/api/")
    ]
    return ReconContext(
        target_url=base,
        live_endpoints=sorted(links | {base}),
        api_endpoints=api_paths,
        auth_endpoints=[f"{base}/login"],
        parameter_bearing_urls=[f"{base}/api/data/10?id=10"],
        has_api=True,
        has_login_page=True,
        crawled_paths=sorted({"/", "/login", "/api/docs", "/api/data/10"}),
    )


class FakeResult:
    def __init__(self, success: bool = True, stdout: str = "") -> None:
        self.success = success
        self.stdout = stdout
        self.stderr = ""


class LabRunner:
    """Executes each tool name as real HTTP against the lab."""

    def __init__(self, base: str) -> None:
        self.base = base
        self.sandbox_dir = None
        self.calls: list[tuple[str, list[str]]] = []
        self.hits: list[tuple[str, str, int]] = []
        jar = http.cookiejar.CookieJar()
        self._http = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar)
        )
        self._authenticate("user1", "welcome1")

    def _authenticate(self, username: str, password: str) -> None:
        request = urllib.request.Request(
            f"{self.base}/login",
            data=json.dumps({"username": username, "password": password}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        self._http.open(request, timeout=5).read()

    def run(self, tool: str, args: list[str], timeout: int = 0) -> FakeResult:
        self.calls.append((tool, list(args)))
        targets = [arg for arg in args if isinstance(arg, str) and arg.startswith(self.base)]
        stdout_lines: list[str] = []
        for target in targets:
            try:
                with self._http.open(target, timeout=5) as response:
                    status = response.status
                    body = response.read().decode()
            except urllib.error.HTTPError as exc:
                status, body = exc.code, exc.read().decode()
            self.hits.append((tool, target, status))
            # The vulnerable endpoint returns another user's record with a 200;
            # the secure twin returns 403, so only the leak becomes a finding.
            leaked_owner = None
            if status == 200 and "/api/data/" in target:
                try:
                    leaked_owner = json.loads(body).get("owner")
                except json.JSONDecodeError:
                    leaked_owner = None
            if leaked_owner == "user2":
                stdout_lines.append(
                    json.dumps(
                        {
                            "template-id": "idor-ownership",
                            "matched-at": target,
                            "info": {"name": "IDOR", "severity": "high"},
                            "type": "IDOR",
                        }
                    )
                )
        return FakeResult(success=True, stdout="\n".join(stdout_lines))


def _authorizer(base: str):
    def allowed(target: str, _engagement) -> bool:
        return target.rstrip("/").startswith(base)

    return allowed


def test_each_real_specialist_runs_on_discovered_lab_signals(lab):
    _post_marker(lab)
    context = discover(lab)
    runner = LabRunner(lab)

    with patch("agent.swarm._is_authorized_target", side_effect=_authorizer(lab)):
        for cls in (IDORAgent, AuthAgent, APIAgent):
            agent = cls(None, runner, context, "eng-lab")
            assert agent.should_activate(), f"{cls.DOMAIN} did not activate on lab signals"
            findings = agent.run()
            assert agent.tools_executed, f"{cls.DOMAIN} executed no tool"
            assert all(f["source_agent"] == agent.DOMAIN for f in findings)

    assert runner.calls
    # The leak was exercised through the vulnerable endpoint, as user1.
    assert any(
        "/api/data/" in target and status == 200 for _tool, target, status in runner.hits
    )
    # The secure twin was only ever refused, never read.
    secure = [status for _tool, target, status in runner.hits if "/api/secure/data/" in target]
    assert secure and all(status == 403 for status in secure), secure

    with urllib.request.urlopen(f"{lab}/__lab/requests", timeout=5) as response:
        log = json.loads(response.read())["requests"]
    leaked = [entry for entry in log if entry["path"].startswith("/api/data/")]
    assert leaked, "no target-side traffic was recorded"
    assert all(entry["identity"] == "user1" for entry in leaked)
    assert not any("sentinel" in entry["path"] for entry in log)


def test_orchestrator_completes_all_three_specialists_and_emits_events(lab, caplog):
    _post_marker(lab)
    context = discover(lab)
    runner = LabRunner(lab)
    orchestrator = SwarmOrchestrator(
        llm_service=None,
        tool_runner=runner,
        recon_context=context,
        engagement_id="eng-lab-orchestrator",
    )

    with patch("agent.swarm._is_authorized_target", side_effect=_authorizer(lab)):
        with caplog.at_level(logging.INFO, logger="agent.swarm"):
            findings, tools = orchestrator.run(timeout=120)

    events = [
        json.loads(record.getMessage().split("[SWARM_EVENT] ", 1)[1])
        for record in caplog.records
        if "[SWARM_EVENT]" in record.getMessage()
    ]
    for domain in ("idor", "auth", "api"):
        assert any(
            event["domain"] == domain and event["event"] == "agent_started"
            for event in events
        ), f"{domain} never started"
        assert any(
            event["domain"] == domain
            and event["event"] == "tool_executed"
            and event["status"] == "success"
            for event in events
        ), f"{domain} never executed a tool"
        assert any(
            event["domain"] == domain
            and event["event"] == "agent_completed"
            and event["status"] == "completed"
            for event in events
        ), f"{domain} did not complete cleanly"
    assert tools
    assert isinstance(findings, list)
