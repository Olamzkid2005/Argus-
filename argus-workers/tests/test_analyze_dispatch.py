"""
Tests for tasks.analyze — post-exploitation and reporting dispatch logic (Gap 5.1).
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

# ── Module-level mocks for OpenTelemetry and Celery ──
_otel = MagicMock()
_otel.trace = MagicMock()
_otel.trace.get_tracer.return_value = MagicMock()
_otel_exporter = MagicMock()
_otel_otlp = MagicMock()
_otel_proto = MagicMock()
_otel_http = MagicMock()
_otel_http.trace_exporter = MagicMock()
_otel_proto.http = _otel_http
_otel_otlp.proto = _otel_proto
_otel_exporter.otlp = _otel_otlp
_otel_sdk = MagicMock()
_otel_sdk.resources = MagicMock()
_otel_sdk.trace = MagicMock()
_otel_sdk.trace.export = MagicMock()
_otel.exporter = _otel_exporter
_otel.sdk = _otel_sdk

_mock_app = MagicMock()
_mock_app.task = lambda **kwargs: lambda f: f
_mock_celery = type(sys)("celery_app")
_mock_celery.app = _mock_app

_heavy_deps = patch.dict(
    sys.modules, {
        "opentelemetry": _otel, "opentelemetry.trace": _otel.trace,
        "opentelemetry.exporter": _otel_exporter, "opentelemetry.exporter.otlp": _otel_otlp,
        "opentelemetry.exporter.otlp.proto": _otel_proto,
        "opentelemetry.exporter.otlp.proto.http": _otel_http,
        "opentelemetry.exporter.otlp.proto.http.trace_exporter": _otel_http.trace_exporter,
        "opentelemetry.sdk": _otel_sdk, "opentelemetry.sdk.resources": _otel_sdk.resources,
        "opentelemetry.sdk.trace": _otel_sdk.trace,
        "opentelemetry.sdk.trace.export": _otel_sdk.trace.export,
        "celery_app": _mock_celery,
    },
)
_heavy_deps.start()
from tasks.analyze import run_analysis
import tasks.analyze as _ta_mod
_heavy_deps.stop()


def _result(needs_post_exploitation=False):
    return {
        "phase": "analyze", "status": "completed", "actions": [],
        "analysis": {"risk_level": "high", "coverage_gaps": [], "high_value_targets": []},
        "scored_findings": [], "reasoning": "", "synthesis": {}, "hypotheses": [],
        "next_state": "reporting", "needs_post_exploitation": needs_post_exploitation,
        "trace_id": "trace-001",
    }


@pytest.fixture(autouse=True)
def _mocks():
    with patch.dict(sys.modules, {
        "opentelemetry": _otel, "opentelemetry.trace": _otel.trace,
        "opentelemetry.exporter": _otel_exporter, "opentelemetry.exporter.otlp": _otel_otlp,
        "opentelemetry.exporter.otlp.proto": _otel_proto,
        "opentelemetry.exporter.otlp.proto.http": _otel_http,
        "opentelemetry.exporter.otlp.proto.http.trace_exporter": _otel_http.trace_exporter,
        "opentelemetry.sdk": _otel_sdk, "opentelemetry.sdk.resources": _otel_sdk.resources,
        "opentelemetry.sdk.trace": _otel_sdk.trace,
        "opentelemetry.sdk.trace.export": _otel_sdk.trace.export,
    }):
        yield


def _patch_ctx(mock_ctx):
    """Replace tasks.analyze.task_context with a mock that yields mock_ctx."""
    orig = _ta_mod.task_context
    mock_fn = MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=mock_ctx), __exit__=MagicMock()))
    _ta_mod.task_context = mock_fn
    return lambda: setattr(_ta_mod, "task_context", orig)


def _run(mock_task, mock_ctx, eng_state="analyzing", **extra_kw):
    restore = _patch_ctx(mock_ctx)
    try:
        with patch("tasks.utils.get_engagement_state", return_value=eng_state):
            # Directly set send_task on the module-level app to avoid patch wiring issues
            _ta_mod.app.send_task = MagicMock()
            ms = _ta_mod.app.send_task
            try:
                result = run_analysis(mock_task, engagement_id="test-eng-001", budget={}, trace_id="trace-001", **extra_kw)
            except Exception:
                result = {"error": "exception", "send_task": ms}
            return result, ms
    finally:
        restore()


class TestPostExploitDispatch:
    def test_dispatches_post_exploit_when_foothold(self, mock_task, mock_ctx):
        mock_ctx.orchestrator.run_analysis.return_value = _result(needs_post_exploitation=True)
        result, ms = _run(mock_task, mock_ctx)
        assert result["status"] == "completed"
        mock_ctx.state.safe_transition.assert_any_call("post_exploitation", "Foothold detected — advancing to post-exploitation")
        ms.assert_called_once_with("tasks.post_exploit.run_post_exploit", args=["test-eng-001", {}, "trace-001"])

    def test_uses_safe_transition_for_post_exploit(self, mock_task, mock_ctx):
        mock_ctx.orchestrator.run_analysis.return_value = _result(needs_post_exploitation=True)
        _, ms = _run(mock_task, mock_ctx)
        mock_ctx.state.safe_transition.assert_called_with("post_exploitation", "Foothold detected — advancing to post-exploitation")
        mock_ctx.state.transition.assert_not_called()


class TestReportDispatch:
    def test_dispatches_report_when_no_foothold(self, mock_task, mock_ctx):
        mock_ctx.orchestrator.run_analysis.return_value = _result(needs_post_exploitation=False)
        result, ms = _run(mock_task, mock_ctx)
        assert result["status"] == "completed"
        mock_ctx.state.transition.assert_called_with("reporting", "Analysis complete — advancing to report")
        ms.assert_called_once_with("tasks.report.generate_report", args=["test-eng-001", "trace-001", {}])
        mock_ctx.state.safe_transition.assert_not_called()

    def test_uses_regular_transition_for_reporting(self, mock_task, mock_ctx):
        mock_ctx.orchestrator.run_analysis.return_value = _result(needs_post_exploitation=False)
        _, ms = _run(mock_task, mock_ctx)
        mock_ctx.state.transition.assert_called_once()


class TestStateTransitionFailure:
    def test_handles_post_exploit_transition_failure(self, mock_task, mock_ctx):
        mock_ctx.orchestrator.run_analysis.return_value = _result(needs_post_exploitation=True)
        mock_ctx.state.safe_transition.side_effect = [RuntimeError("Invalid transition"), None]
        result, ms = _run(mock_task, mock_ctx)
        assert result["status"] == "failed" and result["reason"] == "state_transition_failed"
        assert mock_ctx.state.safe_transition.call_count == 2

    def test_handles_report_transition_failure(self, mock_task, mock_ctx):
        mock_ctx.orchestrator.run_analysis.return_value = _result(needs_post_exploitation=False)
        mock_ctx.state.transition.side_effect = RuntimeError("DB locked")
        result, ms = _run(mock_task, mock_ctx)
        assert result["status"] == "failed" and result["reason"] == "state_transition_failed"
        mock_ctx.state.safe_transition.assert_called_with("failed", "State transition failed: DB locked")


class TestTaskDispatchFailure:
    def test_handles_post_exploit_dispatch_failure(self, mock_task, mock_ctx):
        mock_ctx.orchestrator.run_analysis.return_value = _result(needs_post_exploitation=True)
        restore = _patch_ctx(mock_ctx)
        orig_send = _ta_mod.app.send_task
        try:
            with patch("tasks.utils.get_engagement_state", return_value="analyzing"):
                _ta_mod.app.send_task = MagicMock(side_effect=ConnectionError("Redis unavailable"))
                result = run_analysis(mock_task, engagement_id="test-eng-001", budget={}, trace_id="trace-001")
        finally:
            _ta_mod.app.send_task = orig_send
            restore()
        assert result["status"] == "failed" and result["reason"] == "post_exploit_dispatch_failed"
        mock_ctx.state.safe_transition.assert_any_call("failed", "Failed to enqueue post-exploitation: Redis unavailable")

    def test_handles_report_dispatch_failure(self, mock_task, mock_ctx):
        mock_ctx.orchestrator.run_analysis.return_value = _result(needs_post_exploitation=False)
        restore = _patch_ctx(mock_ctx)
        orig_send = _ta_mod.app.send_task
        try:
            with patch("tasks.utils.get_engagement_state", return_value="analyzing"):
                _ta_mod.app.send_task = MagicMock(side_effect=ConnectionError("Broker unreachable"))
                result = run_analysis(mock_task, engagement_id="test-eng-001", budget={}, trace_id="trace-001")
        finally:
            _ta_mod.app.send_task = orig_send
            restore()
        assert result["status"] == "failed" and result["reason"] == "report_dispatch_failed"
        mock_ctx.state.transition.assert_called_once()


class TestIdempotency:
    def test_skips_if_already_reporting(self, mock_task, mock_ctx):
        result, _ = _run(mock_task, mock_ctx, eng_state="reporting")
        assert result["status"] == "skipped" and result["reason"] == "already_reporting"
        mock_ctx.orchestrator.run_analysis.assert_not_called()

    def test_skips_if_already_complete(self, mock_task, mock_ctx):
        result, _ = _run(mock_task, mock_ctx, eng_state="complete")
        assert result["status"] == "skipped" and result["reason"] == "already_complete"
        mock_ctx.orchestrator.run_analysis.assert_not_called()

    def test_skips_if_already_failed(self, mock_task, mock_ctx):
        result, _ = _run(mock_task, mock_ctx, eng_state="failed")
        assert result["status"] == "skipped" and result["reason"] == "already_failed"
        mock_ctx.orchestrator.run_analysis.assert_not_called()


class TestBugBountyModeForwarding:
    def test_forwards_bug_bounty_mode(self, mock_task, mock_ctx):
        mock_ctx.orchestrator.run_analysis.return_value = _result(needs_post_exploitation=False)
        mock_fn = MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=mock_ctx), __exit__=MagicMock()))
        _ta_mod.task_context = mock_fn
        try:
            with patch("tasks.utils.get_engagement_state", return_value="analyzing"):
                with patch("tasks.analyze.app.send_task"):
                    run_analysis(mock_task, engagement_id="test-eng-001", budget={}, trace_id="trace-001", bug_bounty_mode=True)
        finally:
            _ta_mod.task_context = mock_fn._mock_wraps if hasattr(mock_fn, "_mock_wraps") else lambda: None
        assert mock_fn.call_args[1]["job_extra"]["bug_bounty_mode"] is True

    def test_omits_bug_bounty_mode_when_none(self, mock_task, mock_ctx):
        mock_ctx.orchestrator.run_analysis.return_value = _result(needs_post_exploitation=False)
        mock_fn = MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=mock_ctx), __exit__=MagicMock()))
        _ta_mod.task_context = mock_fn
        try:
            with patch("tasks.utils.get_engagement_state", return_value="analyzing"):
                with patch("tasks.analyze.app.send_task"):
                    run_analysis(mock_task, engagement_id="test-eng-001", budget={}, trace_id="trace-001")
        finally:
            _ta_mod.task_context = mock_fn._mock_wraps if hasattr(mock_fn, "_mock_wraps") else lambda: None
        assert "bug_bounty_mode" not in mock_fn.call_args[1]["job_extra"]


# ── Reusable fixtures ──

@pytest.fixture
def mock_task():
    t = MagicMock()
    t.request.id = "celery-task-001"
    return t

@pytest.fixture
def mock_ctx():
    c = MagicMock()
    c.engagement_id = "test-eng-001"
    c.job = {"type": "analyze", "engagement_id": "test-eng-001", "budget": {}, "trace_id": "trace-001"}
    c.trace_id = "trace-001"
    c.orchestrator = MagicMock()
    c.state = MagicMock()
    c.db_conn_string = "pg://test:test@localhost/test"
    return c
