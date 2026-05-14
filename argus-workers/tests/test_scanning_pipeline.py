"""
Scanning pipeline contract tests.

Maps to the Argus validation plan:
- Phase 1: trace_id propagation across Celery hand-offs (Stage 3 — scanning).
- Stage 3: downstream analyze dispatch uses the same trace as the scan task context.

These tests mock Redis, DB, locks, and orchestrator; they assert invariants only.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def engagement_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def trace_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def budget() -> dict:
    return {"max_cycles": 3, "max_depth": 2}


class _CapturingContext:
    """Minimal context manager for patching task_context."""

    def __init__(self, ctx):
        self._ctx = ctx

    def __enter__(self):
        return self._ctx

    def __exit__(self, *args):
        return False


def test_run_scan_propagates_trace_id_to_analyze_enqueue(
    engagement_id: str, trace_id: str, budget: dict
):
    """Analyze task must receive the same trace_id as task_context (no silent fork)."""
    from tasks import scan as scan_module

    ctx = MagicMock()
    ctx.trace_id = trace_id
    ctx.orchestrator.run_scan.return_value = {
        "phase": "scan",
        "status": "completed",
        "findings_count": 0,
        "next_state": "analyzing",
        "trace_id": trace_id,
    }
    ctx.state = MagicMock()

    captured_send: dict = {}

    def fake_send_task(name, args=None, kwargs=None, **kw):
        captured_send["name"] = name
        captured_send["args"] = list(args or ())
        m = MagicMock()
        m.id = "fake-analyze-id"
        return m

    mock_app = MagicMock()
    mock_app.send_task.side_effect = fake_send_task

    def task_context_factory(*a, **kw):
        return _CapturingContext(ctx)

    with (
        patch.object(scan_module, "task_context", side_effect=task_context_factory),
        patch.object(scan_module, "app", mock_app),
        patch("tasks.utils.load_recon_context", return_value=None),
    ):
        out = scan_module.run_scan.run(
            engagement_id,
            ["https://example.test/"],
            budget,
            trace_id,
            True,
        )

    assert captured_send.get("name") == "tasks.analyze.run_analysis"
    assert captured_send.get("args") == [engagement_id, budget, trace_id]
    assert out.get("analysis_task_id") == "fake-analyze-id"
    assert out.get("status") == "completed"


def test_run_scan_task_context_receives_trace_agent_targets_in_job_extra(
    engagement_id: str, trace_id: str, budget: dict
):
    """job_extra must carry targets, budget, agent_mode, recon_context for orchestrator.run_scan."""
    from tasks import scan as scan_module

    ctx = MagicMock()
    ctx.trace_id = trace_id
    ctx.orchestrator.run_scan.return_value = {
        "phase": "scan",
        "status": "completed",
        "findings_count": 2,
        "next_state": "analyzing",
        "trace_id": trace_id,
    }
    ctx.state = MagicMock()

    last_tc_kwargs: dict = {}

    def capture_task_context(task, eid, job_type, job_extra=None, trace_id=None, current_state=None):
        last_tc_kwargs.update(
            {
                "job_extra": job_extra,
                "trace_id": trace_id,
                "job_type": job_type,
            }
        )
        tid = trace_id or str(uuid.uuid4())
        ctx.trace_id = tid
        je = job_extra or {}
        ctx.job = {"type": job_type, "engagement_id": eid, "trace_id": tid, **je}
        return _CapturingContext(ctx)

    targets = ["https://a.example/", "https://b.example/"]

    with (
        patch.object(scan_module, "task_context", side_effect=capture_task_context),
        patch.object(scan_module, "app") as mock_app,
        patch("tasks.utils.load_recon_context", return_value=None),
    ):
        mock_app.send_task.return_value = MagicMock(id="analyze-id")
        scan_module.run_scan.run(
            engagement_id,
            targets,
            budget,
            trace_id,
            False,
        )

    assert last_tc_kwargs.get("trace_id") == trace_id
    extra = last_tc_kwargs.get("job_extra") or {}
    assert extra.get("targets") == targets
    assert extra.get("budget") == budget
    assert extra.get("agent_mode") is False
    assert "recon_context" in extra
    ctx.orchestrator.run_scan.assert_called_once()
    job = ctx.orchestrator.run_scan.call_args[0][0]
    assert job["type"] == "scan"
    assert job["engagement_id"] == engagement_id
    assert job["trace_id"] == trace_id
    assert job["targets"] == targets
    assert job["agent_mode"] is False


def test_run_scan_marks_failed_when_analyze_enqueue_raises(
    engagement_id: str, trace_id: str, budget: dict
):
    from tasks import scan as scan_module

    ctx = MagicMock()
    ctx.trace_id = trace_id
    ctx.orchestrator.run_scan.return_value = {
        "phase": "scan",
        "status": "completed",
        "findings_count": 1,
        "next_state": "analyzing",
        "trace_id": trace_id,
    }
    ctx.state = MagicMock()

    mock_app = MagicMock()
    mock_app.send_task.side_effect = RuntimeError("broker down")

    with (
        patch.object(scan_module, "task_context", side_effect=lambda *a, **kw: _CapturingContext(ctx)),
        patch.object(scan_module, "app", mock_app),
        patch("tasks.utils.load_recon_context", return_value=None),
    ):
        scan_module.run_scan.run(
            engagement_id,
            ["https://example.test/"],
            budget,
            trace_id,
            True,
        )

    fail_calls = [
        c for c in ctx.state.transition.call_args_list if c[0][0] == "failed"
    ]
    assert fail_calls, "expected failed transition when analyze enqueue fails"
    assert "broker down" in fail_calls[0][0][1]
