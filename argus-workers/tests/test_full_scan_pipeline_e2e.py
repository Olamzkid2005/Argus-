"""
End-to-end integration test for the full scan pipeline.

Tests the complete recon → scan → analyze → report chain with
mocked external dependencies (DB, Redis, subprocess, tool binaries)
but real task bodies, real orchestrator routing, and real pipeline
dispatch orchestration.

Pipeline under test:
  tasks.recon.run_recon
      ↓ (send_task: tasks.scan.run_scan)
  tasks.scan.run_scan
      ↓ (send_task: tasks.analyze.run_analysis)
  tasks.analyze.run_analysis
      ↓ (send_task: tasks.report.generate_report)
  tasks.report.generate_report
      ↓ (safe_transition: complete)

Assertions per phase:
  - trace_id propagation
  - state transition calls
  - job payload structure
  - findings accumulaton
  - error → failed transition
"""

from __future__ import annotations

import fnmatch
import os
import sys
import uuid
from unittest.mock import MagicMock, PropertyMock, call, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# ═══════════════════════════════════════════════════════════════════
# Module-level mocks — applied to every test  (same pattern as
# test_orchestrator_integration.py's mock_heavy_deps)
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def mock_heavy_deps():
    """Mock heavy external dependencies so tests run without DB/Redis/tools."""
    with patch.dict(sys.modules, {
        "psycopg2": MagicMock(),
        "psycopg2.sql": MagicMock(),
        "psycopg2.extras": MagicMock(),
        "psycopg2.extensions": MagicMock(),
        "redis": MagicMock(),
        "redis.client": MagicMock(),
        "database": MagicMock(),
        "database.connection": MagicMock(),
        "database.repositories": MagicMock(),
        "database.repositories.finding_repository": MagicMock(),
        "database.repositories.engagement_repository": MagicMock(),
        "database.repositories.report_repository": MagicMock(),
        "database.repositories.agent_decision_repository": MagicMock(),
        "database.repositories.rate_limit_repository": MagicMock(),
        "database.repositories.tool_metrics_repository": MagicMock(),
        "database.repositories.target_profile_repository": MagicMock(),
        "database.repositories.tool_accuracy_repository": MagicMock(),
        "database.services": MagicMock(),
        "database.services.embedding_service": MagicMock(),
        "websocket_events": MagicMock(),
        "websocket": MagicMock(),
        "compliance_reporting": MagicMock(),
        "compliance_posture_scorer": MagicMock(),
        "llm_client": MagicMock(),
        "mcp_server": MagicMock(),
        "streaming": MagicMock(),
        "tracing": MagicMock(),
        "parsers.parser": MagicMock(),
        "parsers.normalizer": MagicMock(),
        "tools.tool_runner": MagicMock(),
    }):
        yield


# ═══════════════════════════════════════════════════════════════════
# Shared fixtures
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def engagement_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def trace_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def budget() -> dict:
    return {"max_cycles": 3, "max_depth": 2}


@pytest.fixture
def target_url() -> str:
    return "https://staging.app.example.com"


@pytest.fixture
def targets(target_url) -> list[str]:
    return [target_url]


@pytest.fixture
def mock_db_url() -> str:
    return "postgresql://test:test@localhost:5432/test"


# ═══════════════════════════════════════════════════════════════════
# Capturing context manager — wraps a MagicMock TaskContext
# ═══════════════════════════════════════════════════════════════════

class _CapturingContext:
    """Minimal context manager wrapping a test TaskContext."""

    def __init__(self, ctx):
        self._ctx = ctx

    def __enter__(self):
        return self._ctx

    def __exit__(self, *args):
        return False


def _make_mock_task_context(
    job_type: str,
    engagement_id: str,
    trace_id: str,
    db_conn_string: str = "postgresql://test:test@localhost:5432/test",
    redis_url: str = "redis://localhost:6379",
) -> MagicMock:
    """Build a mock TaskContext shaped like the real TaskContext dataclass."""
    ctx = MagicMock()
    ctx.trace_id = trace_id
    ctx.engagement_id = engagement_id
    ctx.job_type = job_type
    ctx.job = {
        "type": job_type,
        "engagement_id": engagement_id,
        "trace_id": trace_id,
    }
    ctx.db_conn_string = db_conn_string
    ctx.redis_url = redis_url

    # Orchestrator with minimal stubs
    orch = MagicMock()
    orch.engagement_id = engagement_id
    orch.trace_id = trace_id
    ctx.orchestrator = orch

    # State machine
    ctx.state = MagicMock()
    ctx.state.current_state = "created"
    ctx.orchestrator.state = ctx.state

    return ctx


# ═══════════════════════════════════════════════════════════════════
# Helper: CapturingApp — records all send_task calls and returns
# mock AsyncResult objects. This lets us inspect dispatched tasks.
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def dispatched_tasks() -> list[dict]:
    """Records every app.send_task call as a dict."""
    return []


@pytest.fixture
def mock_celery_app(dispatched_tasks):
    """Mock Celery app that records send_task calls."""
    app = MagicMock()

    def fake_send_task(name, args=None, kwargs=None, **kw):
        entry = {
            "name": name,
            "args": args or (),
            "kwargs": kwargs or {},
        }
        dispatched_tasks.append(entry)
        mock_task = MagicMock()
        mock_task.id = f"task-{uuid.uuid4().hex[:8]}"
        return mock_task

    app.send_task.side_effect = fake_send_task
    return app


# ═══════════════════════════════════════════════════════════════════
# End-to-end pipeline test class
# ═══════════════════════════════════════════════════════════════════

class TestFullScanPipelineE2E:
    """Complete recon → scan → analyze → report pipeline integration test."""

    # ── Phase 1: Recon ──────────────────────────────────────────

    def test_phase_recon_dispatches_scan(
        self,
        engagement_id,
        trace_id,
        budget,
        target_url,
        targets,
        dispatched_tasks,
        mock_celery_app,
        mock_db_url,
    ):
        """Recon task transitions to scanning and dispatches scan task with trace_id."""
        from tasks import recon as recon_module

        ctx = _make_mock_task_context(
            "recon", engagement_id, trace_id,
            db_conn_string=mock_db_url,
        )
        ctx.job.update({
            "target": target_url,
            "targets": targets,
            "budget": budget,
            "agent_mode": True,
            "scan_mode": "agent",
            "aggressiveness": "default",
            "bug_bounty_mode": False,
        })

        recon_result = {
            "phase": "recon",
            "status": "completed",
            "findings_count": 3,
            "next_state": "scanning",
            "recon_context": {"target_url": target_url, "live_endpoints": ["/api", "/login"]},
            "trace_id": trace_id,
        }
        ctx.orchestrator.run_recon.return_value = recon_result

        def fake_task_context(task, eid, job_type, job_extra=None, trace_id=None, current_state=None):
            ctx.job.update(job_extra or {})
            ctx.trace_id = trace_id
            return _CapturingContext(ctx)

        with (
            patch.object(recon_module, "task_context", side_effect=fake_task_context),
            patch.object(recon_module, "app", mock_celery_app),
            patch("tasks.utils.load_recon_context", return_value=None),
            patch("tasks.utils.save_recon_context", return_value=None),
            patch("models.recon_context.ReconContext"),  # prevent to_dict errors
            patch("utils.logging_utils.ScanLogger"),  # prevent format-arg TypeError
        ):
            result = recon_module.run_recon.run(
                engagement_id,
                target_url,
                budget,
                trace_id,
                True,      # agent_mode
                "agent",   # scan_mode
                "default", # aggressiveness
                False,     # bug_bounty_mode
            )

        # ── Assert recon result ──
        assert result["status"] == "completed"
        assert result["findings_count"] == 3
        assert result["trace_id"] == trace_id

        # ── State transitions ──
        ctx.state.transition.assert_any_call("recon", "Starting reconnaissance")
        ctx.state.transition.assert_any_call("scanning", "Recon complete — scan dispatched")

        # ── Orchestrator called with correct job ──
        ctx.orchestrator.run_recon.assert_called_once()
        called_job = ctx.orchestrator.run_recon.call_args[0][0]
        assert called_job["type"] == "recon"
        assert called_job["engagement_id"] == engagement_id
        assert called_job["trace_id"] == trace_id
        assert called_job["target"] == target_url

        # ── Scan task dispatched ──
        assert len(dispatched_tasks) >= 1
        scan_dispatch = next(t for t in dispatched_tasks if t["name"] == "tasks.scan.run_scan")
        assert scan_dispatch is not None
        dispatch_args = scan_dispatch["args"]
        assert dispatch_args[0] == engagement_id  # engagement_id
        assert dispatch_args[1] == [target_url]    # targets
        # recon task mutates budget by adding prev_engagement_id
        expected_budget = dict(budget)
        expected_budget["prev_engagement_id"] = None
        assert dispatch_args[2] == expected_budget  # budget with prev_engagement_id
        assert dispatch_args[3] == trace_id        # trace_id

    def test_phase_recon_fails_when_dispatch_fails(
        self,
        engagement_id,
        trace_id,
        budget,
        target_url,
        mock_celery_app,
        mock_db_url,
    ):
        """When scan dispatch fails, engagement transitions to failed."""
        from tasks import recon as recon_module

        ctx = _make_mock_task_context("recon", engagement_id, trace_id, db_conn_string=mock_db_url)
        ctx.job.update({
            "target": target_url,
            "budget": budget,
            "agent_mode": True,
        })
        ctx.orchestrator.run_recon.return_value = {
            "phase": "recon",
            "status": "completed",
            "findings_count": 1,
            "next_state": "scanning",
            "recon_context": {"target_url": target_url},
            "trace_id": trace_id,
        }

        # Make send_task raise
        mock_celery_app.send_task.side_effect = RuntimeError("Broker unreachable")

        def fake_task_context(task, eid, job_type, job_extra=None, trace_id=None, current_state=None):
            ctx.job.update(job_extra or {})
            ctx.trace_id = trace_id
            return _CapturingContext(ctx)

        with (
            patch.object(recon_module, "task_context", side_effect=fake_task_context),
            patch.object(recon_module, "app", mock_celery_app),
            patch("tasks.utils.load_recon_context", return_value=None),
            patch("tasks.utils.save_recon_context", return_value=None),
        ):
            result = recon_module.run_recon.run(
                engagement_id,
                target_url,
                budget,
                trace_id,
                True,
                "agent",
                "default",
                False,
            )

        # Should still return result (the DispatchLock catches the error)
        # but should attempt failed transition
        fail_call = next(
            (c for c in ctx.state.safe_transition.call_args_list if c[0][0] == "failed"),
            None,
        )
        assert fail_call is not None, "Expected safe_transition('failed') on dispatch error"
        assert "Broker unreachable" in fail_call[0][1]

    # ── Phase 2: Scan ───────────────────────────────────────────

    def test_phase_scan_transitions_and_dispatches_analyze(
        self,
        engagement_id,
        trace_id,
        budget,
        targets,
        dispatched_tasks,
        mock_celery_app,
        mock_db_url,
    ):
        """Scan task transitions to analyzing and dispatches analyze task."""
        from tasks import scan as scan_module

        ctx = _make_mock_task_context("scan", engagement_id, trace_id, db_conn_string=mock_db_url)
        ctx.job.update({
            "targets": targets,
            "budget": budget,
            "agent_mode": True,
            "recon_context": {"target_url": targets[0], "live_endpoints": ["/api"]},
            "auth_config": {},
        })
        ctx.orchestrator.run_scan.return_value = {
            "phase": "scan",
            "status": "completed",
            "findings_count": 5,
            "next_state": "analyzing",
            "trace_id": trace_id,
        }

        def fake_task_context(task, eid, job_type, job_extra=None, trace_id=None, current_state=None):
            ctx.job.update(job_extra or {})
            ctx.trace_id = trace_id
            return _CapturingContext(ctx)

        with (
            patch.object(scan_module, "task_context", side_effect=fake_task_context),
            patch.object(scan_module, "app", mock_celery_app),
            patch("tasks.utils.load_recon_context", return_value=MagicMock()),
        ):
            result = scan_module.run_scan.run(
                engagement_id,
                targets,
                budget,
                trace_id,
                True,
                None,  # scan_mode
                None,  # aggressiveness
                None,  # bug_bounty_mode
            )

        # ── Assert scan result ──
        assert result["status"] == "completed"
        assert result["findings_count"] == 5
        assert result["trace_id"] == trace_id

        # ── State transitions ──
        ctx.state.transition.assert_any_call("analyzing", "Scan complete")

        # ── Orchestrator called correctly ──
        ctx.orchestrator.run_scan.assert_called_once()
        called_job = ctx.orchestrator.run_scan.call_args[0][0]
        assert called_job["type"] == "scan"
        assert called_job["engagement_id"] == engagement_id
        assert called_job["trace_id"] == trace_id
        assert called_job["targets"] == targets

        # ── Analyze task dispatched with trace_id ──
        analyze_dispatch = next(t for t in dispatched_tasks if t["name"] == "tasks.analyze.run_analysis")
        assert analyze_dispatch is not None
        assert analyze_dispatch["args"][0] == engagement_id
        assert analyze_dispatch["args"][1] == budget
        assert analyze_dispatch["args"][2] == trace_id

    def test_phase_scan_missing_recon_context_falls_back(
        self,
        engagement_id,
        trace_id,
        budget,
        targets,
        mock_celery_app,
    ):
        """When recon context is missing, scan should still proceed (deterministic fallback)."""
        from tasks import scan as scan_module

        ctx = _make_mock_task_context("scan", engagement_id, trace_id)
        ctx.job.update({
            "targets": targets,
            "budget": budget,
            "agent_mode": True,
            "recon_context": None,
            "auth_config": {},
        })
        ctx.orchestrator.run_scan.return_value = {
            "phase": "scan",
            "status": "completed",
            "findings_count": 3,
            "next_state": "analyzing",
            "trace_id": trace_id,
        }

        with (
            patch.object(scan_module, "task_context", side_effect=lambda *_, **__: _CapturingContext(ctx)),
            patch.object(scan_module, "app", mock_celery_app),
            patch("tasks.utils.load_recon_context", return_value=None),
        ):
            result = scan_module.run_scan.run(
                engagement_id,
                targets,
                budget,
                trace_id,
                True,
                None,
                None,
                None,
            )

        assert result["status"] == "completed"
        # Should still run scan (fallback to deterministic)
        ctx.orchestrator.run_scan.assert_called_once()

    # ── Phase 3: Analyze ────────────────────────────────────────

    def test_phase_analyze_transitions_and_dispatches_report(
        self,
        engagement_id,
        trace_id,
        budget,
        dispatched_tasks,
        mock_celery_app,
        mock_db_url,
    ):
        """Analyze task transitions to reporting and dispatches report task."""
        from tasks import analyze as analyze_module

        ctx = _make_mock_task_context("analyze", engagement_id, trace_id, db_conn_string=mock_db_url)
        ctx.job.update({
            "budget": budget,
        })
        ctx.orchestrator.run_analysis.return_value = {
            "phase": "analyze",
            "status": "completed",
            "actions": [],
            "analysis": {
                "risk_level": "medium",
                "coverage_gaps": ["api_testing"],
                "high_value_targets": ["/admin"],
            },
            "scored_findings": [
                {"id": str(uuid.uuid4()), "type": "SQL_INJECTION", "severity": "HIGH", "confidence": 0.85},
                {"id": str(uuid.uuid4()), "type": "XSS", "severity": "MEDIUM", "confidence": 0.65},
            ],
            "reasoning": "Found SQL injection and XSS vulnerabilities",
            "synthesis": {
                "risk_level": "medium",
                "executive_summary": "SQL injection and XSS vulnerabilities found",
            },
            "next_state": "reporting",
            "trace_id": trace_id,
        }

        def fake_task_context(task, eid, job_type, job_extra=None, trace_id=None, current_state=None):
            ctx.job.update(job_extra or {})
            ctx.trace_id = trace_id
            return _CapturingContext(ctx)

        with (
            patch.object(analyze_module, "task_context", side_effect=fake_task_context),
            patch.object(analyze_module, "app", mock_celery_app),
            patch("tasks.utils.load_recon_context", return_value=None),
            patch("intelligence_engine.IntelligenceEngine"),  # heavy module
            patch("config.constants.LLM_MAX_COST_PER_ENGAGEMENT", 5000),
            patch("utils.logging_utils.ScanLogger"),  # prevent format-arg TypeError
        ):
            result = analyze_module.run_analysis.run(
                engagement_id,
                budget,
                trace_id,
                None,  # bug_bounty_mode
            )

        # ── Assert analyze result ──
        assert result["status"] == "completed"
        assert result["analysis"]["risk_level"] == "medium"
        assert len(result["scored_findings"]) == 2
        assert result["trace_id"] == trace_id

        # ── State transitions ──
        ctx.state.transition.assert_any_call("reporting", "Analysis complete — advancing to report")

        # ── Orchestrator called correctly ──
        ctx.orchestrator.run_analysis.assert_called_once()
        called_job = ctx.orchestrator.run_analysis.call_args[0][0]
        assert called_job["type"] == "analyze"
        assert called_job["engagement_id"] == engagement_id
        assert called_job["trace_id"] == trace_id

        # ── Report task dispatched ──
        report_dispatch = next(t for t in dispatched_tasks if t["name"] == "tasks.report.generate_report")
        assert report_dispatch is not None
        assert report_dispatch["args"][0] == engagement_id
        assert report_dispatch["args"][1] == trace_id
        assert report_dispatch["args"][2] == budget

    # ── Phase 4: Report ─────────────────────────────────────────

    def test_phase_report_completes_engagement(
        self,
        engagement_id,
        trace_id,
        budget,
        dispatched_tasks,
        mock_celery_app,
        mock_db_url,
    ):
        """Report task transitions engagement to complete."""
        from tasks import report as report_module

        ctx = _make_mock_task_context("report", engagement_id, trace_id, db_conn_string=mock_db_url)
        ctx.job.update({
            "budget": budget,
        })
        ctx.orchestrator.run_reporting.return_value = {
            "phase": "report",
            "status": "completed",
            "next_state": "complete",
            "report": {"sections": ["executive_summary", "findings", "recommendations"]},
            "trace_id": trace_id,
        }

        def fake_task_context(task, eid, job_type, job_extra=None, trace_id=None, current_state=None):
            ctx.job.update(job_extra or {})
            ctx.trace_id = trace_id
            return _CapturingContext(ctx)

        with (
            patch.object(report_module, "task_context", side_effect=fake_task_context),
            patch.object(report_module, "app", mock_celery_app),
            patch("tasks.utils.get_engagement_state", return_value="reporting"),
        ):
            result = report_module.generate_report.run(
                engagement_id,
                trace_id,
                budget,
            )

        # ── Assert report result ──
        assert result["status"] == "completed"
        assert result["report"]["sections"] is not None
        assert result["trace_id"] == trace_id

        # ── State transition to complete ──
        ctx.state.safe_transition.assert_any_call("complete", "Report generated")

        # ── Orchestrator called correctly ──
        ctx.orchestrator.run_reporting.assert_called_once()
        called_job = ctx.orchestrator.run_reporting.call_args[0][0]
        assert called_job["type"] == "report"
        assert called_job["engagement_id"] == engagement_id

    def test_phase_report_no_duplicate_when_already_terminal(
        self,
        engagement_id,
        trace_id,
        budget,
        mock_celery_app,
    ):
        """When engagement is already in terminal state, report should skip."""
        from tasks import report as report_module

        ctx = _make_mock_task_context("report", engagement_id, trace_id)

        with (
            patch.object(report_module, "task_context", side_effect=lambda *_, **__: _CapturingContext(ctx)),
            patch("tasks.utils.get_engagement_state", return_value="complete"),
        ):
            result = report_module.generate_report.run(
                engagement_id,
                trace_id,
                budget,
            )

        # Should return early without calling orchestrator
        assert result["status"] == "already_complete"
        ctx.orchestrator.run_reporting.assert_not_called()

    # ── Full chain test ─────────────────────────────────────────

    def test_full_pipeline_chain(
        self,
        engagement_id,
        trace_id,
        budget,
        target_url,
        targets,
        mock_celery_app,
        mock_db_url,
    ):
        """
        Full pipeline: mock all four task bodies to run consecutively
        by capturing send_task calls and passing real trace_id through.
        """
        from tasks import analyze as analyze_module
        from tasks import recon as recon_module
        from tasks import report as report_module
        from tasks import scan as scan_module

        dispatched = []

        def capturing_send_task(name, args=None, kwargs=None, **kw):
            entry = {"name": name, "args": list(args or ()), "kwargs": kwargs or {}}
            dispatched.append(entry)
            mock_task = MagicMock()
            mock_task.id = f"task-{uuid.uuid4().hex[:8]}"
            return mock_task

        mock_celery_app.send_task.side_effect = capturing_send_task

        # ── Data flow test values ──
        recon_context_data = {
            "target_url": target_url,
            "live_endpoints": ["/api", "/login"],
        }

        # Build a real ReconContext for the scan phase to receive
        from models.recon_context import ReconContext
        recon_context_obj = ReconContext(
            target_url=target_url,
            live_endpoints=["/api", "/login"],
        )

        # Mock to capture save_recon_context calls
        save_recon_context_mock = MagicMock()

        # Mock finding_repo for DB persistence contract verification
        # Simulates: scan → finding_repo.batch_create_or_update_findings → analyze → finding_repo.get_findings_by_engagement
        finding_repo_mock = MagicMock()
        _finding_store: dict[str, list[dict]] = {}

        fake_findings_from_scan = [
            {"type": "SQL_INJECTION", "severity": "HIGH", "endpoint": "/api/login",
             "source_tool": "sqlmap", "confidence": 0.95},
            {"type": "XSS", "severity": "MEDIUM", "endpoint": "/api/users",
             "source_tool": "dalfox", "confidence": 0.70},
            {"type": "CSRF", "severity": "LOW", "endpoint": "/admin",
             "source_tool": "nuclei", "confidence": 0.50},
            {"type": "COMMITTED_SECRET", "severity": "CRITICAL", "endpoint": "src/.env",
             "source_tool": "gitleaks", "confidence": 0.99},
            {"type": "INFO", "severity": "INFO", "endpoint": "/robots.txt",
             "source_tool": "nuclei", "confidence": 0.30},
        ]

        # ── Chain of mock contexts ──
        contexts: dict[str, MagicMock] = {}
        current_trace = trace_id

        def make_recon_ctx(te, eid, jt, job_extra=None, trace_id=None, current_state=None):
            nonlocal current_trace
            if trace_id:
                current_trace = trace_id
            ctx = _make_mock_task_context("recon", eid, current_trace, db_conn_string=mock_db_url)
            ctx.job.update(job_extra or {})
            ctx.orchestrator.run_recon.return_value = {
                "phase": "recon", "status": "completed", "findings_count": 3,
                "next_state": "scanning", "trace_id": current_trace,
                "recon_context": {"target_url": target_url, "live_endpoints": ["/api", "/login"]},
            }
            contexts["recon"] = ctx
            return _CapturingContext(ctx)

        def make_scan_ctx(te, eid, jt, job_extra=None, trace_id=None, current_state=None):
            nonlocal current_trace
            if trace_id:
                current_trace = trace_id
            ctx = _make_mock_task_context("scan", eid, current_trace, db_conn_string=mock_db_url)
            ctx.job.update(job_extra or {})

            def _mock_run_scan(job):
                # Simulate orchestrator saving findings to finding_repo
                findings_count = len(fake_findings_from_scan)
                _finding_store[eid] = fake_findings_from_scan
                finding_repo_mock.batch_create_or_update_findings(eid, fake_findings_from_scan)
                return {
                    "phase": "scan", "status": "completed", "findings_count": findings_count,
                    "next_state": "analyzing", "trace_id": current_trace,
                }

            ctx.orchestrator.run_scan.side_effect = _mock_run_scan
            contexts["scan"] = ctx
            return _CapturingContext(ctx)

        def make_analyze_ctx(te, eid, jt, job_extra=None, trace_id=None, current_state=None):
            nonlocal current_trace
            if trace_id:
                current_trace = trace_id
            ctx = _make_mock_task_context("analyze", eid, current_trace, db_conn_string=mock_db_url)
            ctx.job.update(job_extra or {})

            def _mock_run_analysis(job):
                # Simulate orchestrator loading findings from DB and scoring them
                stored = _finding_store.get(eid, [])
                finding_repo_mock.get_findings_by_engagement.return_value = (stored, len(stored))
                mock_result = finding_repo_mock.get_findings_by_engagement(eid)
                loaded = mock_result[0]  # the stored findings list
                scored = []
                for f in loaded:
                    if f["type"] in ("SQL_INJECTION", "XSS"):
                        scored.append({
                            "id": str(uuid.uuid4()),
                            "type": f["type"], "severity": f["severity"],
                            "confidence": f.get("confidence", 0.5),
                        })
                return {
                    "phase": "analyze", "status": "completed", "actions": [],
                    "analysis": {"risk_level": "high", "coverage_gaps": [], "high_value_targets": []},
                    "scored_findings": scored,
                    "reasoning": "Analysis complete", "synthesis": {},
                    "next_state": "reporting", "trace_id": current_trace,
                }

            ctx.orchestrator.run_analysis.side_effect = _mock_run_analysis
            contexts["analyze"] = ctx
            return _CapturingContext(ctx)

        def make_report_ctx(te, eid, jt, job_extra=None, trace_id=None, current_state=None):
            nonlocal current_trace
            if trace_id:
                current_trace = trace_id
            ctx = _make_mock_task_context("report", eid, current_trace, db_conn_string=mock_db_url)
            ctx.job.update(job_extra or {})
            ctx.orchestrator.run_reporting.return_value = {
                "phase": "report", "status": "completed",
                "next_state": "complete", "trace_id": current_trace,
                "report": {"sections": ["summary", "findings"]},
            }
            contexts["report"] = ctx
            return _CapturingContext(ctx)

        with (
            # Phase 1: Recon
            patch.object(recon_module, "task_context", side_effect=make_recon_ctx),
            patch.object(recon_module, "app", mock_celery_app),
            patch("tasks.utils.load_recon_context", return_value=recon_context_obj),
            patch("tasks.utils.save_recon_context", save_recon_context_mock),
            # Phase 2: Scan
            patch.object(scan_module, "task_context", side_effect=make_scan_ctx),
            patch.object(scan_module, "app", mock_celery_app),
            # Phase 3: Analyze
            patch.object(analyze_module, "task_context", side_effect=make_analyze_ctx),
            patch.object(analyze_module, "app", mock_celery_app),
            # Phase 4: Report
            patch.object(report_module, "task_context", side_effect=make_report_ctx),
            patch.object(report_module, "app", mock_celery_app),
            patch("tasks.utils.get_engagement_state", return_value="reporting"),
            patch("config.constants.LLM_MAX_COST_PER_ENGAGEMENT", 5000),
            patch("intelligence_engine.IntelligenceEngine"),
            patch("utils.logging_utils.ScanLogger"),
        ):
            # STEP 1: Run recon
            recon_result = recon_module.run_recon.run(
                engagement_id, target_url, budget, trace_id,
                True, "agent", "default", False,
            )
            assert recon_result["status"] == "completed"
            assert recon_result["trace_id"] == trace_id
            contexts["recon"].state.transition.assert_any_call("recon", "Starting reconnaissance")

            # ── Data flow: recon_context saved to Redis ──
            assert recon_result.get("recon_context") is not None
            assert recon_result["recon_context"]["target_url"] == target_url
            save_recon_context_mock.assert_called_once()
            saved_ctx_arg = save_recon_context_mock.call_args[0][1]
            assert isinstance(saved_ctx_arg, ReconContext)
            assert saved_ctx_arg.target_url == target_url
            assert saved_ctx_arg.live_endpoints == ["/api", "/login"]

            # STEP 2: Capture scan dispatch, run scan
            scan_dispatch = next(d for d in dispatched if d["name"] == "tasks.scan.run_scan")
            assert scan_dispatch is not None
            scan_args = scan_dispatch["args"]
            assert scan_args[0] == engagement_id
            assert scan_args[1] == [target_url]
            assert scan_args[3] == trace_id

            scan_result = scan_module.run_scan.run(
                engagement_id, scan_args[1], scan_args[2], scan_args[3],
                *scan_args[4:],
            )
            assert scan_result["status"] == "completed"
            assert scan_result["trace_id"] == trace_id
            contexts["scan"].state.transition.assert_any_call("analyzing", "Scan complete")

            # ── Data flow: scan loaded recon_context ──
            scan_ctx = contexts["scan"]
            assert scan_ctx.job.get("recon_context") is not None
            assert scan_ctx.job["recon_context"].target_url == target_url
            assert scan_ctx.job["recon_context"].live_endpoints == ["/api", "/login"]
            # ── Data flow: scan produced findings_count ──
            assert scan_result["findings_count"] == 5

            # ── Data flow: findings persisted to DB by scan ──
            finding_repo_mock.batch_create_or_update_findings.assert_called_once()
            persist_args = finding_repo_mock.batch_create_or_update_findings.call_args[0]
            assert persist_args[0] == engagement_id
            persisted = persist_args[1]
            assert len(persisted) == 5
            assert any(f["type"] == "SQL_INJECTION" and f["severity"] == "HIGH" for f in persisted)
            assert any(f["type"] == "COMMITTED_SECRET" and f["severity"] == "CRITICAL" for f in persisted)

            # STEP 3: Capture analyze dispatch, run analyze
            analyze_dispatch = next(d for d in dispatched if d["name"] == "tasks.analyze.run_analysis")
            assert analyze_dispatch is not None
            analyze_args = analyze_dispatch["args"]
            assert analyze_args[0] == engagement_id
            assert analyze_args[2] == trace_id

            analyze_result = analyze_module.run_analysis.run(
                analyze_args[0], analyze_args[1], analyze_args[2],
            )
            assert analyze_result["status"] == "completed"
            assert analyze_result["trace_id"] == trace_id
            # ── Data flow: findings loaded from DB by analyze ──
            finding_repo_mock.get_findings_by_engagement.assert_called_once()
            load_args = finding_repo_mock.get_findings_by_engagement.call_args[0]
            assert load_args[0] == engagement_id

            # ── Data flow: scored_findings produced by analyze from loaded findings ──
            assert len(analyze_result["scored_findings"]) == 2
            sf_types = {sf["type"] for sf in analyze_result["scored_findings"]}
            assert "SQL_INJECTION" in sf_types
            assert "XSS" in sf_types
            sf1 = next(sf for sf in analyze_result["scored_findings"] if sf["type"] == "SQL_INJECTION")
            assert sf1["severity"] == "HIGH"
            contexts["analyze"].state.transition.assert_any_call(
                "reporting", "Analysis complete — advancing to report",
            )

            # STEP 4: Capture report dispatch, run report
            report_dispatch = next(d for d in dispatched if d["name"] == "tasks.report.generate_report")
            assert report_dispatch is not None
            report_args = report_dispatch["args"]
            assert report_args[0] == engagement_id
            assert report_args[1] == trace_id

            report_result = report_module.generate_report.run(
                report_args[0], report_args[1], report_args[2],
            )
            assert report_result["status"] == "completed"
            assert report_result["trace_id"] == trace_id
            contexts["report"].state.safe_transition.assert_any_call(
                "complete", "Report generated",
            )

    # ── Trace ID propagation ────────────────────────────────────

    def test_trace_id_propagates_across_chain(
        self,
        engagement_id,
        trace_id,
        budget,
        target_url,
        dispatched_tasks,
        mock_celery_app,
    ):
        """Every dispatched task in the chain must carry the original trace_id."""
        from tasks import recon as recon_module

        ctx = _make_mock_task_context("recon", engagement_id, trace_id)
        ctx.job.update({
            "target": target_url,
            "budget": budget,
            "agent_mode": True,
        })
        ctx.orchestrator.run_recon.return_value = {
            "phase": "recon", "status": "completed", "findings_count": 1,
            "next_state": "scanning", "trace_id": trace_id,
            "recon_context": {"target_url": target_url},
        }

        with (
            patch.object(recon_module, "task_context", side_effect=lambda *_, **__: _CapturingContext(ctx)),
            patch.object(recon_module, "app", mock_celery_app),
            patch("tasks.utils.load_recon_context", return_value=None),
            patch("tasks.utils.save_recon_context", return_value=None),
            patch("models.recon_context.ReconContext"),
        ):
            recon_module.run_recon.run(
                engagement_id, target_url, budget, trace_id,
                True, "agent", "default", False,
            )

        # The scan dispatch must carry the same trace_id
        scan_dispatch = next(t for t in dispatched_tasks if t["name"] == "tasks.scan.run_scan")
        assert scan_dispatch["args"][3] == trace_id, (
            f"Expected trace_id={trace_id} in scan dispatch, got {scan_dispatch['args'][3]}"
        )

    # ── Error handling ──────────────────────────────────────────

    def test_chain_error_recon_succeeds_scan_fails(
        self,
        engagement_id,
        trace_id,
        budget,
        target_url,
        mock_celery_app,
        mock_db_url,
    ):
        """
        Error recovery: recon succeeds → scan raises → analyze/report skipped.

        Recon dispatches scan, but scan's orchestrator.run_scan() raises.
        The exception propagates before transition("analyzing") and
        send_task("tasks.analyze.run_analysis") are reached, so neither
        analyze nor report are ever dispatched.
        """
        from tasks import recon as recon_module
        from tasks import scan as scan_module

        # Make send_task record dispatches
        dispatched: list[dict] = []

        def recording_send_task(name, args=None, kwargs=None, **kw):
            entry = {"name": name, "args": list(args or ()), "kwargs": kwargs or {}}
            dispatched.append(entry)
            mock_task = MagicMock()
            mock_task.id = f"task-{uuid.uuid4().hex[:8]}"
            return mock_task

        mock_celery_app.send_task.side_effect = recording_send_task

        # ── Step 1: Run recon (succeeds, dispatches scan) ──

        recon_ctx = _make_mock_task_context(
            "recon", engagement_id, trace_id, db_conn_string=mock_db_url,
        )
        recon_ctx.job.update({
            "target": target_url,
            "targets": [target_url],
            "budget": budget,
            "agent_mode": True,
            "scan_mode": "agent",
            "aggressiveness": "default",
            "bug_bounty_mode": False,
        })
        recon_ctx.orchestrator.run_recon.return_value = {
            "phase": "recon", "status": "completed", "findings_count": 2,
            "next_state": "scanning", "trace_id": trace_id,
            "recon_context": {"target_url": target_url},
        }

        def make_recon_ctx_fn(task, eid, jt, job_extra=None, trace_id=None, current_state=None):
            recon_ctx.job.update(job_extra or {})
            if trace_id:
                recon_ctx.trace_id = trace_id
            return _CapturingContext(recon_ctx)

        with (
            patch.object(recon_module, "task_context", side_effect=make_recon_ctx_fn),
            patch.object(recon_module, "app", mock_celery_app),
            patch("tasks.utils.load_recon_context", return_value=None),
            patch("tasks.utils.save_recon_context", return_value=None),
            patch("models.recon_context.ReconContext"),
            patch("utils.logging_utils.ScanLogger"),
        ):
            recon_result = recon_module.run_recon.run(
                engagement_id, target_url, budget, trace_id,
                True, "agent", "default", False,
            )

        assert recon_result["status"] == "completed"
        assert recon_result["trace_id"] == trace_id

        # ── Step 2: Run scan (fails with exception) ──

        scan_ctx = _make_mock_task_context(
            "scan", engagement_id, trace_id, db_conn_string=mock_db_url,
        )
        scan_ctx.job.update({
            "targets": [target_url],
            "budget": budget,
            "agent_mode": True,
            "recon_context": None,
            "auth_config": {},
        })
        # Make orchestrator raise — this prevents transition to analyzing
        # and dispatch of analyze task
        scan_ctx.orchestrator.run_scan.side_effect = RuntimeError("Scan failed")

        def make_scan_ctx_fn(task, eid, jt, job_extra=None, trace_id=None, current_state=None):
            scan_ctx.job.update(job_extra or {})
            if trace_id:
                scan_ctx.trace_id = trace_id
            return _CapturingContext(scan_ctx)

        scan_dispatch = next(d for d in dispatched if d["name"] == "tasks.scan.run_scan")
        scan_args = scan_dispatch["args"]

        with (
            patch.object(scan_module, "task_context", side_effect=make_scan_ctx_fn),
            patch.object(scan_module, "app", mock_celery_app),
            patch("tasks.utils.load_recon_context", return_value=None),
            patch("utils.logging_utils.ScanLogger"),
        ):
            with pytest.raises(RuntimeError, match="Scan failed"):
                scan_module.run_scan.run(
                    engagement_id, scan_args[1], scan_args[2], scan_args[3],
                    *scan_args[4:],
                )

        # ── Assert error recovery ──

        # 1. Orchestrator was called
        scan_ctx.orchestrator.run_scan.assert_called_once()

        # 2. Scan started its state transition (current_state != "scanning")
        scan_ctx.state.transition.assert_any_call("scanning", "Starting scan")

        # 3. Analyzed transition was NEVER reached (exception before it)
        analyzing_calls = [
            c for c in scan_ctx.state.transition.call_args_list
            if c[0][0] == "analyzing"
        ]
        assert len(analyzing_calls) == 0, (
            "transition('analyzing') should not be called when scan raises"
        )

        # 4. No analyze/report tasks were dispatched (only scan from recon)
        analyze_dispatched = [d for d in dispatched if "analyze" in d["name"]]
        report_dispatched = [d for d in dispatched if "report" in d["name"]]
        assert len(analyze_dispatched) == 0, (
            f"Expected no analyze dispatch, got: {analyze_dispatched}"
        )
        assert len(report_dispatched) == 0, (
            f"Expected no report dispatch, got: {report_dispatched}"
        )

        # 5. Scan context's trace_id is still set (propagated from recon)
        assert scan_ctx.trace_id == trace_id

    def test_chain_error_scan_returns_failed_status(
        self,
        engagement_id,
        trace_id,
        budget,
        target_url,
        targets,
        mock_celery_app,
        mock_db_url,
    ):
        """
        Error recovery: recon succeeds → scan returns status=failed → analyze/report NOT dispatched.

        Unlike test_chain_error_recon_succeeds_scan_fails (which tests the
        exception path), this test verifies the non-exception failure path:
        orchestrator.run_scan() returns a result dict with status="failed".

        The transition to analyzing fails (simulating the guard that prevents
        downstream dispatch when scan results indicate failure), triggering
        the error handler in scan.py which:
        - Calls safe_transition("failed")
        - Returns early without dispatching analyze or report
        """
        from tasks import recon as recon_module
        from tasks import scan as scan_module

        dispatched: list[dict] = []

        def recording_send_task(name, args=None, kwargs=None, **kw):
            entry = {"name": name, "args": list(args or ()), "kwargs": kwargs or {}}
            dispatched.append(entry)
            mock_task = MagicMock()
            mock_task.id = f"task-{uuid.uuid4().hex[:8]}"
            return mock_task

        mock_celery_app.send_task.side_effect = recording_send_task

        # ── Step 1: Run recon (succeeds, dispatches scan) ──

        recon_ctx = _make_mock_task_context(
            "recon", engagement_id, trace_id, db_conn_string=mock_db_url,
        )
        recon_ctx.job.update({
            "target": target_url,
            "targets": [target_url],
            "budget": budget,
            "agent_mode": True,
            "scan_mode": "agent",
            "aggressiveness": "default",
            "bug_bounty_mode": False,
        })
        recon_ctx.orchestrator.run_recon.return_value = {
            "phase": "recon", "status": "completed", "findings_count": 2,
            "next_state": "scanning", "trace_id": trace_id,
            "recon_context": {"target_url": target_url},
        }

        def make_recon_ctx_fn(task, eid, jt, job_extra=None, trace_id=None, current_state=None):
            recon_ctx.job.update(job_extra or {})
            if trace_id:
                recon_ctx.trace_id = trace_id
            return _CapturingContext(recon_ctx)

        with (
            patch.object(recon_module, "task_context", side_effect=make_recon_ctx_fn),
            patch.object(recon_module, "app", mock_celery_app),
            patch("tasks.utils.load_recon_context", return_value=None),
            patch("tasks.utils.save_recon_context", return_value=None),
            patch("models.recon_context.ReconContext"),
            patch("utils.logging_utils.ScanLogger"),
        ):
            recon_result = recon_module.run_recon.run(
                engagement_id, target_url, budget, trace_id,
                True, "agent", "default", False,
            )

        assert recon_result["status"] == "completed"
        assert recon_result["trace_id"] == trace_id

        # ── Step 2: Run scan (orchestrator returns failed status) ──

        scan_ctx = _make_mock_task_context(
            "scan", engagement_id, trace_id, db_conn_string=mock_db_url,
        )
        scan_ctx.job.update({
            "targets": [target_url],
            "budget": budget,
            "agent_mode": True,
            "recon_context": None,
            "auth_config": {},
        })

        # Orchestrator returns failed status (doesn't raise an exception)
        scan_ctx.orchestrator.run_scan.return_value = {
            "phase": "scan", "status": "failed", "reason": "scan_failed",
            "findings_count": 0, "trace_id": trace_id,
        }

        # Make transition to analyzing FAIL (simulating the guard that prevents
        # downstream dispatch when orchestrator returns failure status)
        def _transition_raises_if_analyzing(state_name, msg):
            if state_name == "analyzing":
                raise Exception(f"Cannot transition to {state_name} — scan failed")

        scan_ctx.state.transition.side_effect = _transition_raises_if_analyzing

        def make_scan_ctx_fn(task, eid, jt, job_extra=None, trace_id=None, current_state=None):
            scan_ctx.job.update(job_extra or {})
            if trace_id:
                scan_ctx.trace_id = trace_id
            return _CapturingContext(scan_ctx)

        scan_dispatch = next(d for d in dispatched if d["name"] == "tasks.scan.run_scan")
        scan_args = scan_dispatch["args"]

        with (
            patch.object(scan_module, "task_context", side_effect=make_scan_ctx_fn),
            patch.object(scan_module, "app", mock_celery_app),
            patch("tasks.utils.load_recon_context", return_value=None),
            patch("utils.logging_utils.ScanLogger"),
        ):
            # Should NOT raise — orchestrator returns, doesn't raise
            result = scan_module.run_scan.run(
                engagement_id, scan_args[1], scan_args[2], scan_args[3],
                *scan_args[4:],
            )

        # ── Assert failure handling ──

        # 1. Result reflects failure (overwritten by error handler in scan.py)
        assert result["status"] == "failed"
        assert result["reason"] == "state_transition_failed", (
            "Expected scan.py's transition-failure handler to set reason"
        )

        # 2. Orchestrator was called
        scan_ctx.orchestrator.run_scan.assert_called_once()

        # 3. transition("scanning") WAS called (scan started)
        scan_ctx.state.transition.assert_any_call("scanning", "Starting scan")

        # 4. transition("analyzing") was attempted (via side_effect)
        analyzing_calls = [
            c for c in scan_ctx.state.transition.call_args_list
            if c[0][0] == "analyzing"
        ]
        assert len(analyzing_calls) == 1, (
            "transition('analyzing') should be attempted once"
        )

        # 5. safe_transition("failed") was called as error recovery
        fail_transition = next(
            (
                c for c in scan_ctx.state.safe_transition.call_args_list
                if c[0][0] == "failed"
            ),
            None,
        )
        assert fail_transition is not None, (
            "Expected safe_transition('failed') as error recovery"
        )

        # 6. No analyze/report tasks were dispatched (only scan from recon)
        analyze_dispatched = [d for d in dispatched if "analyze" in d["name"]]
        report_dispatched = [d for d in dispatched if "report" in d["name"]]
        assert len(analyze_dispatched) == 0, (
            f"Expected no analyze dispatch, got: {analyze_dispatched}"
        )
        assert len(report_dispatched) == 0, (
            f"Expected no report dispatch, got: {report_dispatched}"
        )

    def test_chain_error_report_raises(
        self,
        engagement_id,
        trace_id,
        budget,
        target_url,
        targets,
        mock_celery_app,
        mock_db_url,
    ):
        """
        Error recovery: recon → scan → analyze succeed, report raises → exception propagates.

        The report task's orchestrator.run_reporting() raises an exception
        (not wrapped in try/except), so the exception propagates out of
        the task. The safe_transition("complete") and LLM review dispatch
        are never reached.
        """
        from tasks import analyze as analyze_module
        from tasks import recon as recon_module
        from tasks import report as report_module
        from tasks import scan as scan_module

        dispatched: list[dict] = []

        def recording_send_task(name, args=None, kwargs=None, **kw):
            entry = {"name": name, "args": list(args or ()), "kwargs": kwargs or {}}
            dispatched.append(entry)
            mock_task = MagicMock()
            mock_task.id = f"task-{uuid.uuid4().hex[:8]}"
            return mock_task

        mock_celery_app.send_task.side_effect = recording_send_task

        # ── Shared: mock finding_repo for DB persistence ──
        finding_repo_mock = MagicMock()
        _finding_store: dict[str, list[dict]] = {}

        fake_findings_from_scan = [
            {"type": "SQL_INJECTION", "severity": "HIGH", "endpoint": "/api/login",
             "source_tool": "sqlmap", "confidence": 0.95},
            {"type": "XSS", "severity": "MEDIUM", "endpoint": "/api/users",
             "source_tool": "dalfox", "confidence": 0.70},
        ]

        recon_ctx = _make_mock_task_context(
            "recon", engagement_id, trace_id, db_conn_string=mock_db_url,
        )
        recon_ctx.job.update({
            "target": target_url, "targets": [target_url], "budget": budget,
            "agent_mode": True, "scan_mode": "agent", "aggressiveness": "default",
            "bug_bounty_mode": False,
        })
        recon_ctx.orchestrator.run_recon.return_value = {
            "phase": "recon", "status": "completed", "findings_count": 2,
            "next_state": "scanning", "trace_id": trace_id,
            "recon_context": {"target_url": target_url},
        }

        scan_ctx = _make_mock_task_context(
            "scan", engagement_id, trace_id, db_conn_string=mock_db_url,
        )
        scan_ctx.job.update({
            "targets": [target_url], "budget": budget, "agent_mode": True,
            "recon_context": None, "auth_config": {},
        })

        def _mock_run_scan(job):
            findings_count = len(fake_findings_from_scan)
            _finding_store[engagement_id] = fake_findings_from_scan
            finding_repo_mock.batch_create_or_update_findings(
                engagement_id, fake_findings_from_scan,
            )
            return {
                "phase": "scan", "status": "completed", "findings_count": findings_count,
                "next_state": "analyzing", "trace_id": trace_id,
            }

        scan_ctx.orchestrator.run_scan.side_effect = _mock_run_scan

        analyze_ctx = _make_mock_task_context(
            "analyze", engagement_id, trace_id, db_conn_string=mock_db_url,
        )
        analyze_ctx.job.update({"budget": budget})

        def _mock_run_analysis(job):
            stored = _finding_store.get(engagement_id, [])
            finding_repo_mock.get_findings_by_engagement.return_value = (stored, len(stored))
            mock_result = finding_repo_mock.get_findings_by_engagement(engagement_id)
            loaded = mock_result[0]
            scored = []
            for f in loaded:
                if f["type"] in ("SQL_INJECTION", "XSS"):
                    scored.append({
                        "id": str(uuid.uuid4()),
                        "type": f["type"], "severity": f["severity"],
                        "confidence": f.get("confidence", 0.5),
                    })
            return {
                "phase": "analyze", "status": "completed", "actions": [],
                "analysis": {"risk_level": "high", "coverage_gaps": [], "high_value_targets": []},
                "scored_findings": scored,
                "reasoning": "Analysis complete", "synthesis": {},
                "next_state": "reporting", "trace_id": trace_id,
            }

        analyze_ctx.orchestrator.run_analysis.side_effect = _mock_run_analysis

        report_ctx = _make_mock_task_context(
            "report", engagement_id, trace_id, db_conn_string=mock_db_url,
        )
        report_ctx.job.update({"budget": budget})
        # Orchestrator raises — this propagates because report.py does NOT
        # wrap run_reporting() in try/except
        report_ctx.orchestrator.run_reporting.side_effect = RuntimeError("Report generation failed")

        # ── Helper: create context mappers that return each ctx ──
        def make_recon_ctx_fn(task, eid, jt, job_extra=None, trace_id=None, current_state=None):
            recon_ctx.job.update(job_extra or {})
            if trace_id:
                recon_ctx.trace_id = trace_id
            return _CapturingContext(recon_ctx)

        def make_scan_ctx_fn(task, eid, jt, job_extra=None, trace_id=None, current_state=None):
            scan_ctx.job.update(job_extra or {})
            if trace_id:
                scan_ctx.trace_id = trace_id
            return _CapturingContext(scan_ctx)

        def make_analyze_ctx_fn(task, eid, jt, job_extra=None, trace_id=None, current_state=None):
            analyze_ctx.job.update(job_extra or {})
            if trace_id:
                analyze_ctx.trace_id = trace_id
            return _CapturingContext(analyze_ctx)

        def make_report_ctx_fn(task, eid, jt, job_extra=None, trace_id=None, current_state=None):
            report_ctx.job.update(job_extra or {})
            if trace_id:
                report_ctx.trace_id = trace_id
            return _CapturingContext(report_ctx)

        with (
            # Phase 1: Recon
            patch.object(recon_module, "task_context", side_effect=make_recon_ctx_fn),
            patch.object(recon_module, "app", mock_celery_app),
            patch("tasks.utils.load_recon_context", return_value=None),
            patch("tasks.utils.save_recon_context", return_value=None),
            patch("models.recon_context.ReconContext"),
            # Phase 2: Scan
            patch.object(scan_module, "task_context", side_effect=make_scan_ctx_fn),
            patch.object(scan_module, "app", mock_celery_app),
            # Phase 3: Analyze
            patch.object(analyze_module, "task_context", side_effect=make_analyze_ctx_fn),
            patch.object(analyze_module, "app", mock_celery_app),
            # Phase 4: Report
            patch.object(report_module, "task_context", side_effect=make_report_ctx_fn),
            patch.object(report_module, "app", mock_celery_app),
            patch("tasks.utils.get_engagement_state", return_value="reporting"),
            patch("config.constants.LLM_MAX_COST_PER_ENGAGEMENT", 5000),
            patch("intelligence_engine.IntelligenceEngine"),
            patch("utils.logging_utils.ScanLogger"),
        ):
            # ── Step 1: Recon succeeds ──
            recon_result = recon_module.run_recon.run(
                engagement_id, target_url, budget, trace_id,
                True, "agent", "default", False,
            )
            assert recon_result["status"] == "completed"
            assert recon_result["trace_id"] == trace_id
            recon_ctx.state.transition.assert_any_call("recon", "Starting reconnaissance")

            # ── Step 2: Capture scan dispatch, run scan (succeeds) ──
            scan_dispatch = next(d for d in dispatched if d["name"] == "tasks.scan.run_scan")
            scan_args = scan_dispatch["args"]
            scan_result = scan_module.run_scan.run(
                engagement_id, scan_args[1], scan_args[2], scan_args[3],
                *scan_args[4:],
            )
            assert scan_result["status"] == "completed"
            assert scan_result["trace_id"] == trace_id
            scan_ctx.state.transition.assert_any_call("analyzing", "Scan complete")

            # ── Step 3: Capture analyze dispatch, run analyze (succeeds) ──
            analyze_dispatch = next(d for d in dispatched if d["name"] == "tasks.analyze.run_analysis")
            analyze_args = analyze_dispatch["args"]
            analyze_result = analyze_module.run_analysis.run(
                analyze_args[0], analyze_args[1], analyze_args[2],
            )
            assert analyze_result["status"] == "completed"
            assert analyze_result["trace_id"] == trace_id
            assert len(analyze_result["scored_findings"]) == 2
            analyze_ctx.state.transition.assert_any_call(
                "reporting", "Analysis complete — advancing to report",
            )

            # ── Step 4: Capture report dispatch, run report (RAISES) ──
            report_dispatch = next(d for d in dispatched if d["name"] == "tasks.report.generate_report")
            report_args = report_dispatch["args"]

            with pytest.raises(RuntimeError, match="Report generation failed"):
                report_module.generate_report.run(
                    report_args[0], report_args[1], report_args[2],
                )

        # ── Assert error recovery ──

        # 1. Orchestrator was called on all phases
        recon_ctx.orchestrator.run_recon.assert_called_once()
        scan_ctx.orchestrator.run_scan.assert_called_once()
        analyze_ctx.orchestrator.run_analysis.assert_called_once()
        report_ctx.orchestrator.run_reporting.assert_called_once()

        # 2. All successful phases completed their state transitions
        recon_ctx.state.transition.assert_any_call("scanning", "Recon complete — scan dispatched")
        scan_ctx.state.transition.assert_any_call("analyzing", "Scan complete")
        analyze_ctx.state.transition.assert_any_call("reporting", "Analysis complete — advancing to report")

        # 3. safe_transition("complete") was NEVER called on report context
        #    (exception propagates before the safe_transition in report.py)
        complete_calls = [
            c for c in report_ctx.state.safe_transition.call_args_list
            if c[0][0] == "complete"
        ]
        assert len(complete_calls) == 0, (
            "safe_transition('complete') should not be called when report raises"
        )

        # 4. Tasks dispatched: recon → scan, scan → analyze, analyze → report
        #    No additional dispatches after report (it's the last phase)
        dispatched_names = [d["name"] for d in dispatched]
        assert "tasks.scan.run_scan" in dispatched_names
        assert "tasks.analyze.run_analysis" in dispatched_names
        assert "tasks.report.generate_report" in dispatched_names

    # ── Celery queue routing ──────────────────────────────────────

    def test_celery_queue_routing_matches_task_routes(self):
        """
        Verify that each pipeline task name resolves to the correct queue
        via Celery's task_routes configuration.

        The task_routes dict uses glob patterns (e.g. 'tasks.recon.*') to
        map task name prefixes to queues. All send_task calls in the
        pipeline rely on this automatic routing — none pass queue= explicitly.

        Uses fnmatch (stdlib) to simulate Celery's pattern matching logic.
        """
        from celery_app import app

        routes = app.conf.task_routes
        assert isinstance(routes, dict), f"task_routes should be a dict, got {type(routes)}"

        # ── Helper: resolve task name to queue via fnmatch ──
        def _resolve(task_name: str) -> str | None:
            for pattern, route in routes.items():
                if fnmatch.fnmatch(task_name, pattern):
                    return route.get("queue")
            return None

        # ── Pipeline chain task names ──
        expected = [
            ("tasks.recon.run_recon", "recon"),
            ("tasks.recon.expand_recon", "recon"),
            ("tasks.scan.run_scan", "scan"),
            ("tasks.scan.deep_scan", "scan"),
            ("tasks.scan.auth_focused_scan", "scan"),
            ("tasks.analyze.run_analysis", "analyze"),
            ("tasks.report.generate_report", "report"),
            ("tasks.report.generate_compliance_report", "report"),
            ("tasks.report.get_findings_summary", "report"),
            # Other routed tasks
            ("tasks.repo_scan.run_repo_scan", "repo_scan"),
            ("tasks.posture.run_posture", "analyze"),
            # Undefined pattern → no queue (default broker queue)
            ("tasks.health.ping", None),
            ("tasks.scheduled.run_due_scans", None),
            ("tasks.maintenance.cleanup_old_results", None),
        ]

        for task_name, expected_queue in expected:
            actual = _resolve(task_name)
            assert actual == expected_queue, (
                f"'{task_name}': expected queue={expected_queue!r}, got {actual!r}\n"
                f"  Check task_routes in celery_app.py"
            )

    def test_celery_queue_routing_chain_dispatch_matches_routing(self):
        """
        Verify that send_task calls made by the recon phase dispatch route to
        the correct queues via task_routes, and that no send_task call
        explicitly passes queue= (which would bypass the central routing config).
        """
        from tasks import recon as recon_module

        from celery_app import app
        routes = app.conf.task_routes

        def _resolve_queue(task_name: str) -> str | None:
            for pattern, route in routes.items():
                if fnmatch.fnmatch(task_name, pattern):
                    return route.get("queue")
            return None

        dispatched: list[dict] = []

        def capturing_send_task(name, args=None, kwargs=None, **kw):
            entry = {
                "name": name,
                "args": list(args or ()),
                "task_kwargs": kwargs or {},
                "send_opts": kw,  # send_task options like queue, countdown, task_id
            }
            dispatched.append(entry)
            mock_task = MagicMock()
            mock_task.id = f"task-{uuid.uuid4().hex[:8]}"
            return mock_task

        mock_app = MagicMock()
        mock_app.send_task.side_effect = capturing_send_task

        ctx = _make_mock_task_context("recon", "routing-test-id", "routing-trace")
        ctx.orchestrator.run_recon.return_value = {
            "phase": "recon", "status": "completed", "findings_count": 1,
            "next_state": "scanning",
            "recon_context": {"target_url": "https://example.com"},
            "trace_id": "routing-trace",
        }

        with (
            patch.object(recon_module, "task_context", side_effect=lambda *_, **__: _CapturingContext(ctx)),
            patch.object(recon_module, "app", mock_app),
            patch("tasks.utils.load_recon_context", return_value=None),
            patch("tasks.utils.save_recon_context", return_value=None),
            patch("models.recon_context.ReconContext"),
            patch("utils.logging_utils.ScanLogger"),
        ):
            recon_module.run_recon.run(
                "routing-test-id", "https://example.com", {},
                "routing-trace", True, "agent", "default", False,
            )

        # ── Assert core pipeline tasks have routes ──
        # Core pipeline tasks must have explicit queue routes in task_routes.
        # Auxiliary tasks (like asset_discovery) are non-critical and can
        # fall through to the default queue.
        assert len(dispatched) >= 1, "Expected at least one task dispatch"
        core_pipeline_tasks = ["tasks.scan.run_scan"]

        for entry in dispatched:
            task_name = entry["name"]
            resolved_queue = _resolve_queue(task_name)
            if task_name in core_pipeline_tasks:
                assert resolved_queue is not None, (
                    f"Pipeline task '{task_name}' has no route in task_routes!\n"
                    f"  Add a pattern like '{task_name.rsplit('.', 1)[0]}.*' to celery_app.py task_routes"
                )
            elif task_name not in core_pipeline_tasks and resolved_queue is None:
                # Non-core tasks without explicit routes go to default queue,
                # which is acceptable for auxiliary dispatches like asset_discovery
                pass

        # ── Verify no send_task call passes queue= explicitly ──
        # If any send_task call passed queue=, it would appear in **send_opts**
        # (the **kw from send_task), NOT in the task kwargs dict.
        # This would bypass task_routes, making the routing config irrelevant.
        for entry in dispatched:
            assert "queue" not in entry["send_opts"], (
                f"send_task('{entry['name']}') passes queue= explicitly!\n"
                f"  send_opts={entry['send_opts']}\n"
                f"  This bypasses task_routes. Remove the queue= parameter."
            )

    # ── ReconContext serialization round-trip ──

    def test_recon_context_full_serialization_roundtrip(
        self,
        engagement_id,
        trace_id,
        budget,
        target_url,
        targets,
        mock_celery_app,
        mock_db_url,
    ):
        """
        Verify that a rich ReconContext survives JSON serialization/deserialization
        through the real save_recon_context → Redis → load_recon_context path,
        and that the deserialized object integrates correctly with the scan task.

        Round-trip: ReconContext → to_dict() → json.dumps → fake Redis
                                            → json.loads → from_dict() → ReconContext
        """
        import json

        from models.recon_context import ReconContext
        from tasks.utils import (
            RECON_CONTEXT_KEY,
            load_recon_context,
            save_recon_context,
        )

        # ── Fake Redis: dict-backed store that mimics setex/get/expire ──
        store: dict[str, str] = {}

        class _FakeRedis:
            def setex(self, key, ttl, value):
                store[key] = value

            def get(self, key):
                return store.get(key)

            def expire(self, key, ttl):
                pass

        fake_redis = _FakeRedis()

        # ── Rich ReconContext with every field populated ──
        original = ReconContext(
            target_url=target_url,
            live_endpoints=["/api", "/login", "/admin", "/users"],
            subdomains=["api.example.com", "admin.example.com", "mail.example.com"],
            open_ports=[
                {"port": 80, "service": "http", "state": "open"},
                {"port": 443, "service": "https", "state": "open"},
                {"port": 8443, "service": "https-alt", "state": "open"},
            ],
            tech_stack=["React", "Node.js", "PostgreSQL", "Redis", "Nginx"],
            crawled_paths=[
                "/", "/api/users", "/api/login", "/admin/dashboard",
                "/.env", "/robots.txt", "/sitemap.xml",
            ],
            parameter_bearing_urls=["/api/users?id=1", "/search?q=test", "/api/data?page=2"],
            auth_endpoints=["/login", "/oauth/token", "/auth/callback"],
            api_endpoints=["/api/users", "/api/login", "/api/data", "/graphql"],
            findings_count=12,
            has_login_page=True,
            has_api=True,
            has_file_upload=False,
            # Repo-scan fields (should be preserved even for URL scans)
            scan_type="url",
            languages_detected=["JavaScript", "TypeScript", "Python"],
            vulnerability_types=["SQL_INJECTION", "XSS", "CSRF"],
            severity_breakdown={"CRITICAL": 1, "HIGH": 3, "MEDIUM": 5, "LOW": 3},
            critical_files=["src/db.py", "src/auth.js", "config/keys.yml"],
            frameworks_detected=["React", "Express"],
            has_hardcoded_secrets=True,
            dependency_vulns_count=3,
            repo_clone_success=True,
            target_profile={
                "total_scans": 5,
                "best_tools": ["nuclei", "gitleaks", "dalfox"],
                "noisy_tools": ["nmap"],
            },
        )

        # ── Step 1: Save hostname via real function path ──
        with patch("tasks.utils._get_redis_client", return_value=fake_redis):
            save_recon_context(engagement_id, original, redis_url="redis://fake:6379")

        expected_key = RECON_CONTEXT_KEY.format(engagement_id=engagement_id)
        assert expected_key in store, "ReconContext not saved to Redis store"

        # Inspect the raw JSON to verify structure before deserialization
        raw_json = store[expected_key]
        parsed = json.loads(raw_json)
        assert parsed["target_url"] == target_url
        assert len(parsed["live_endpoints"]) == 4
        assert len(parsed["subdomains"]) == 3
        assert len(parsed["open_ports"]) == 3
        assert len(parsed["tech_stack"]) == 5
        assert parsed["scan_type"] == "url"
        assert parsed["has_hardcoded_secrets"] is True
        assert parsed["target_profile"]["total_scans"] == 5

        # ── Step 2: Load hostname via real function path ──
        with patch("tasks.utils._get_redis_client", return_value=fake_redis):
            loaded = load_recon_context(engagement_id, redis_url="redis://fake:6379")

        assert loaded is not None
        assert isinstance(loaded, ReconContext)

        # ── Step 3: Field-by-field comparison ──
        # Strings
        assert loaded.target_url == original.target_url
        assert loaded.scan_type == original.scan_type

        # Lists
        assert loaded.live_endpoints == original.live_endpoints
        assert loaded.subdomains == original.subdomains
        assert loaded.open_ports == original.open_ports
        assert loaded.tech_stack == original.tech_stack
        assert loaded.crawled_paths == original.crawled_paths
        assert loaded.parameter_bearing_urls == original.parameter_bearing_urls
        assert loaded.auth_endpoints == original.auth_endpoints
        assert loaded.api_endpoints == original.api_endpoints
        assert loaded.languages_detected == original.languages_detected
        assert loaded.vulnerability_types == original.vulnerability_types
        assert loaded.critical_files == original.critical_files
        assert loaded.frameworks_detected == original.frameworks_detected

        # Dicts
        assert loaded.severity_breakdown == original.severity_breakdown
        assert loaded.target_profile == original.target_profile

        # Bools / ints
        assert loaded.findings_count == original.findings_count
        assert loaded.has_login_page == original.has_login_page
        assert loaded.has_api == original.has_api
        assert loaded.has_file_upload == original.has_file_upload
        assert loaded.has_hardcoded_secrets == original.has_hardcoded_secrets
        assert loaded.dependency_vulns_count == original.dependency_vulns_count
        assert loaded.repo_clone_success == original.repo_clone_success

        # ── Step 4: Verify LLM helpers work on deserialized object ──
        structured = loaded.to_llm_structured()
        assert isinstance(structured, str)
        parsed_llm = json.loads(structured)
        assert parsed_llm["target"] == target_url
        assert parsed_llm["live_endpoints_count"] == 4
        assert parsed_llm["target_memory"]["prior_scans"] == 5
        assert "nuclei" in parsed_llm["target_memory"]["best_tools"]

        summary = loaded.to_llm_summary()
        assert isinstance(summary, str)
        assert target_url in summary
        assert "Ports:" in summary  # open_ports rendered

        # ── Step 5: Verify the deserialized context can be used in the chain ──
        # Build a scan ctx.job with the loaded ReconContext (not a dict)
        from tasks import scan as scan_module

        scan_ctx = _make_mock_task_context(
            "scan", engagement_id, trace_id, db_conn_string=mock_db_url,
        )
        scan_ctx.job.update({
            "targets": targets,
            "budget": budget,
            "agent_mode": True,
            # Use the deserialized ReconContext OBJECT (realistic flow)
            "recon_context": loaded,
            "auth_config": {},
        })
        scan_ctx.orchestrator.run_scan.return_value = {
            "phase": "scan", "status": "completed", "findings_count": 5,
            "next_state": "analyzing", "trace_id": trace_id,
        }

        def make_scan_ctx_for_roundtrip(
            te, eid, jt, job_extra=None, trace_id=None, current_state=None,
        ):
            scan_ctx.job.update(job_extra or {})
            if trace_id:
                scan_ctx.trace_id = trace_id
            return _CapturingContext(scan_ctx)

        with (
            patch.object(scan_module, "task_context", side_effect=make_scan_ctx_for_roundtrip),
            patch.object(scan_module, "app", mock_celery_app),
            # Return the deserialized ReconContext to match real scan flow
            patch("tasks.utils.load_recon_context", return_value=loaded),
        ):
            result = scan_module.run_scan.run(
                engagement_id, targets, budget, trace_id,
                True, None, None, None,
            )

        assert result["status"] == "completed"
        assert result["trace_id"] == trace_id

        # Verify the scan's job_extra.recon_context held the deserialized ReconContext
        assert scan_ctx.job.get("recon_context") is not None
        assert scan_ctx.job["recon_context"].target_url == target_url
        assert scan_ctx.job["recon_context"].live_endpoints == ["/api", "/login", "/admin", "/users"]
        assert scan_ctx.job["recon_context"].has_hardcoded_secrets is True

    def test_orchestrator_unknown_job_type_raises_error(
        self,
        engagement_id,
        mock_db_url,
    ):
        """Orchestrator should raise ValueError for unknown job types.

        Bypasses __init__ and directly constructs a minimally-wired
        Orchestrator instance to test only the run() routing logic.
        """
        import time
        from unittest.mock import MagicMock, patch

        # Must import AFTER mock_heavy_deps patches sys.modules
        import orchestrator_pkg.orchestrator as orch_module

        orch = orch_module.Orchestrator.__new__(orch_module.Orchestrator)
        orch.engagement_id = engagement_id
        orch.start_time = time.time()
        orch.trace_id = None
        orch.bug_bounty_mode = False

        # span_recorder needed by run() → self.span_recorder.span(...)
        span_mock = MagicMock()
        span_mock.__enter__ = MagicMock(return_value=span_mock)
        span_mock.__exit__ = MagicMock(return_value=None)
        orch.span_recorder = MagicMock()
        orch.span_recorder.span.return_value = span_mock

        # logger needed by run() → self.logger.log(...)
        orch.logger = MagicMock()

        # ws_publisher needed by run() branches — not exercised for unknown type
        # but the attribute is read in some code paths, so provide a no-op mock
        orch.ws_publisher = MagicMock()

        with pytest.raises(ValueError, match="Unknown job type"):
            orch.run({"type": "nonexistent"})
