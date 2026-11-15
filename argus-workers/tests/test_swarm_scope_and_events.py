"""Stage 7.3: one scope decision for every specialist target, and structured
per-specialist evidence.

The specialists used to append raw recon endpoints after ``_get_targets()``
already filtered scope, so an endpoint outside the allowlist could still be
scanned. These tests fail if any target the agents add skips the shared
``_is_authorized_target`` decision, and they pin the structured events the
live-fire harness asserts on.
"""

from __future__ import annotations

import json
import logging
from unittest.mock import patch

from agent.swarm import APIAgent, AuthAgent, IDORAgent
from models.recon_context import ReconContext

AUTHORIZED = "https://lab.example"
EVIL = "https://evil.example"


class FakeResult:
    def __init__(self, success: bool = True, stdout: str = "", stderr: str = "") -> None:
        self.success = success
        self.stdout = stdout
        self.stderr = stderr


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []
        self.sandbox_dir = None

    def run(self, tool: str, args: list[str], timeout: int = 0) -> FakeResult:
        self.calls.append((tool, list(args)))
        return FakeResult(success=True, stdout="")

    @property
    def targets(self) -> set[str]:
        found: set[str] = set()
        for tool, args in self.calls:
            for arg in args:
                if isinstance(arg, str) and arg.startswith(("http://", "https://")):
                    found.add(arg)
        return found


def _context() -> ReconContext:
    return ReconContext(
        target_url=AUTHORIZED,
        live_endpoints=[f"{AUTHORIZED}/api/data/10", f"{EVIL}/api/data/11"],
        api_endpoints=[f"{AUTHORIZED}/api/data/10", f"{EVIL}/api/data/11"],
        auth_endpoints=[f"{AUTHORIZED}/login", f"{EVIL}/login"],
        parameter_bearing_urls=[f"{AUTHORIZED}/api/data/10?id=1"],
        has_api=True,
        has_login_page=True,
        crawled_paths=["/", "/login", "/api/docs", "/api/data/10", "/api/data/11"],
    )


def _authorizer(target: str, _engagement: str | None) -> bool:
    return target.rstrip("/").startswith(AUTHORIZED)


def test_auth_agent_never_scans_raw_recon_endpoints_outside_scope():
    runner = RecordingRunner()
    agent = AuthAgent(None, runner, _context(), "eng-scope")
    with patch("agent.swarm._is_authorized_target", side_effect=_authorizer):
        agent.run()

    assert runner.calls, "the agent should still scan its authorized targets"
    assert runner.targets == {f"{AUTHORIZED}/api/data/10", f"{AUTHORIZED}/login"}, (
        f"out-of-scope target reached a tool: {runner.targets}"
    )


def test_api_agent_never_scans_raw_recon_endpoints_outside_scope():
    runner = RecordingRunner()
    agent = APIAgent(None, runner, _context(), "eng-scope")
    with patch("agent.swarm._is_authorized_target", side_effect=_authorizer):
        agent.run()

    assert runner.calls
    assert runner.targets == {f"{AUTHORIZED}/api/data/10"}, runner.targets


def test_idor_agent_never_scans_raw_recon_endpoints_outside_scope():
    runner = RecordingRunner()
    agent = IDORAgent(None, runner, _context(), "eng-scope")
    with patch("agent.swarm._is_authorized_target", side_effect=_authorizer):
        agent.run()

    assert runner.calls
    assert runner.targets == {f"{AUTHORIZED}/api/data/10"}, runner.targets


def test_a_specialist_with_no_authorized_targets_runs_nothing():
    runner = RecordingRunner()
    context = _context()
    context.live_endpoints = [f"{EVIL}/api/data/11"]
    context.api_endpoints = [f"{EVIL}/api/data/11"]
    context.auth_endpoints = [f"{EVIL}/login"]
    context.parameter_bearing_urls = []
    agent = APIAgent(None, runner, context, "eng-scope")
    with patch("agent.swarm._is_authorized_target", return_value=False):
        agent.run()
    assert runner.calls == []


def test_tool_selection_and_execution_are_emitted_as_structured_events(caplog):
    runner = RecordingRunner()
    agent = IDORAgent(None, runner, _context(), "eng-events")
    with patch("agent.swarm._is_authorized_target", side_effect=_authorizer):
        with caplog.at_level(logging.INFO, logger="agent.swarm"):
            agent.run()

    events = [
        json.loads(record.getMessage().split("[SWARM_EVENT] ", 1)[1])
        for record in caplog.records
        if "[SWARM_EVENT]" in record.getMessage()
    ]
    assert any(e["event"] == "agent_started" and e["domain"] == "idor" for e in events)
    selected = [e for e in events if e["event"] == "tool_selected"]
    assert selected and all(e["selection"] == "deterministic" for e in selected)
    executed = [e for e in events if e["event"] == "tool_executed"]
    assert executed, "no tool execution was recorded"
    assert all(e["status"] == "success" for e in executed)
    assert all(e["engagement_id"] == "eng-events" for e in events)
    assert agent.tools_executed, "successful tools are not tracked"


def test_failed_tool_execution_is_recorded_truthfully(caplog):
    class FailingRunner(RecordingRunner):
        def run(self, tool: str, args: list[str], timeout: int = 0) -> FakeResult:
            self.calls.append((tool, list(args)))
            return FakeResult(success=False, stderr="boom")

    agent = IDORAgent(None, FailingRunner(), _context(), "eng-fail")
    with patch("agent.swarm._is_authorized_target", side_effect=_authorizer):
        with caplog.at_level(logging.INFO, logger="agent.swarm"):
            agent.run()

    executed = [
        json.loads(record.getMessage().split("[SWARM_EVENT] ", 1)[1])
        for record in caplog.records
        if "[SWARM_EVENT]" in record.getMessage()
        and '"tool_executed"' in record.getMessage()
    ]
    assert executed
    assert all(e["status"] == "failed" for e in executed)
    assert agent.tools_executed == set()
