"""Typed ``task_*`` MCP protocol tests (transport, endpoint and tick wiring).

These tests do not need PostgreSQL: the bridge is exercised against small worker
processes and the endpoint uses an injected executor.
"""

from __future__ import annotations

import sys

import pytest

from control_plane.contracts import ProtocolError
from control_plane.task_service import (
    MAX_REQUEST_BYTES,
    dispatch_task_request,
    parse_task_request,
    set_task_executor,
)
from control_plane.worker_bridge import MCPTaskBridge

ECHO_WORKER = """
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    params = request["params"]
    result = {
        "accepted": True,
        "data": {
            "method": request["method"],
            "task_type": params["task_type"],
            "conclude": params["conclude"],
            "request": params["request"],
        },
    }
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}) + "\\n")
    sys.stdout.flush()
"""

SLOW_WORKER = """
import json
import sys
import time

for line in sys.stdin:
    json.loads(line)
    time.sleep(5)
"""

MALFORMED_WORKER = """
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": "not-an-object"}) + "\\n")
    sys.stdout.flush()
"""


def _bridge(script: str, *, timeout: float = 5.0) -> MCPTaskBridge:
    return MCPTaskBridge([sys.executable, "-c", script], timeout_seconds=timeout)


def test_bridge_sends_typed_task_methods_and_returns_the_result():
    bridge = _bridge(ECHO_WORKER)
    try:
        assert bridge.supports("bootstrap")
        assert bridge.supports("reason")
        assert bridge.supports("explore")
        assert not bridge.supports("generate_subtasks")
        echoed = bridge.bootstrap({"engagement_id": "e-1"}, conclude=True)
        assert echoed["data"]["method"] == "task_bootstrap"
        assert echoed["data"]["task_type"] == "bootstrap"
        assert echoed["data"]["conclude"] is True
        assert echoed["data"]["request"] == {"engagement_id": "e-1"}
        assert bridge.reason({"facts": []})["data"]["method"] == "task_reason"
        assert bridge.explore({"intent": {"id": "i"}})["data"]["method"] == "task_explore"
    finally:
        bridge.close()


def test_bridge_timeout_is_a_timeout_error():
    bridge = _bridge(SLOW_WORKER, timeout=0.3)
    try:
        with pytest.raises(TimeoutError):
            bridge.explore({"sleep": True})
    finally:
        bridge.close()


def test_bridge_rejects_a_non_object_result():
    bridge = _bridge(MALFORMED_WORKER)
    try:
        with pytest.raises(ProtocolError):
            bridge.reason({"facts": []})
    finally:
        bridge.close()


def test_task_request_requires_the_exact_envelope():
    valid = {
        "schema_version": 1,
        "task_type": "reason",
        "conclude": False,
        "request": {"facts": []},
    }
    assert parse_task_request("task_reason", valid).task_type == "reason"
    with pytest.raises(ProtocolError):
        parse_task_request("task_reason", {**valid, "extra": True})
    with pytest.raises(ProtocolError):
        parse_task_request("task_reason", {**valid, "schema_version": 2})
    with pytest.raises(ProtocolError):
        parse_task_request("task_reason", {**valid, "task_type": "explore"})
    with pytest.raises(ProtocolError):
        parse_task_request(
            "task_bootstrap",
            {**valid, "task_type": "bootstrap", "conclude": "yes"},
        )
    with pytest.raises(ProtocolError):
        parse_task_request("unknown_task", valid)


def test_task_request_is_bounded():
    oversized = {
        "schema_version": 1,
        "task_type": "explore",
        "conclude": False,
        "request": {"blob": "x" * (MAX_REQUEST_BYTES + 1)},
    }
    with pytest.raises(ProtocolError):
        parse_task_request("task_explore", oversized)


def test_endpoint_runs_the_configured_executor_once():
    calls = []

    def executor(task_type, request, conclude):
        calls.append((task_type, request, conclude))
        return {"accepted": True, "data": {"description": "one fact"}}

    set_task_executor(executor)
    try:
        result = dispatch_task_request(
            "task_explore",
            {
                "schema_version": 1,
                "task_type": "explore",
                "request": {"intent": {"id": "i-1"}},
            },
        )
    finally:
        set_task_executor(None)
    assert result == {"accepted": True, "data": {"description": "one fact"}}
    assert calls == [("explore", {"intent": {"id": "i-1"}}, False)]


def test_endpoint_without_an_executor_rejects_instead_of_answering(monkeypatch):
    monkeypatch.delenv("ARGUS_TASK_EXECUTOR", raising=False)
    set_task_executor(None)
    result = dispatch_task_request(
        "task_bootstrap",
        {
            "schema_version": 1,
            "task_type": "bootstrap",
            "conclude": True,
            "request": {},
        },
    )
    assert result["accepted"] is False
    assert "executor" in result["error"]


def _control(method: str, task_type: str, request: dict):
    return dispatch_task_request(
        method,
        {
            "schema_version": 1,
            "task_type": task_type,
            "request": request,
        },
    )


def test_generate_subtasks_endpoint_validates_and_orders_a_plan():
    result = _control(
        "task_generate_subtasks",
        "generate_subtasks",
        {
            "task_id": "task-1",
            "subtasks": [
                {"title": "Second", "description": "depends", "depends_on": [2]},
                {"title": "First", "description": "root"},
            ],
        },
    )
    assert result["accepted"] is True
    assert [item["title"] for item in result["data"]["subtasks"]] == [
        "First",
        "Second",
    ]
    assert result["data"]["clamped"] is False

    rejected = _control(
        "task_generate_subtasks",
        "generate_subtasks",
        {"task_id": "task-1", "subtasks": []},
    )
    assert rejected["accepted"] is False


def test_refine_progress_and_cancel_endpoints_are_typed():
    operations = _control(
        "task_refine_subtasks",
        "refine_subtasks",
        {
            "task_id": "task-1",
            "operations": [
                {"op": "ADD", "title": "Check headers", "description": "headers"}
            ],
        },
    )
    assert operations["accepted"] is True
    bad_op = _control(
        "task_refine_subtasks",
        "refine_subtasks",
        {"task_id": "task-1", "operations": [{"op": "REPLACE"}]},
    )
    assert bad_op["accepted"] is False

    progress = _control(
        "task_progress",
        "progress",
        {"task_id": "task-1", "subtask_id": "sub-1", "event": {"tool": "nmap"}},
    )
    assert progress["accepted"] is True
    assert progress["data"]["event"] == {"tool": "nmap"}

    cancelled = _control(
        "task_cancel", "cancel", {"task_id": "task-1", "reason": "operator"}
    )
    assert cancelled["accepted"] is True
    missing_reason = _control(
        "task_cancel", "cancel", {"task_id": "task-1", "reason": " "}
    )
    assert missing_reason["accepted"] is False

    extra = _control(
        "task_progress",
        "progress",
        {
            "task_id": "task-1",
            "subtask_id": "sub-1",
            "event": {},
            "scope": "broaden",
        },
    )
    assert extra["accepted"] is False


def test_endpoint_turns_a_crashed_executor_into_a_rejected_result():
    def boom(*_args):
        raise RuntimeError("provider exploded")

    set_task_executor(boom)
    try:
        result = dispatch_task_request(
            "task_reason",
            {
                "schema_version": 1,
                "task_type": "reason",
                "request": {"facts": []},
            },
        )
    finally:
        set_task_executor(None)
    assert result["accepted"] is False
    assert "provider exploded" in result["error"]
