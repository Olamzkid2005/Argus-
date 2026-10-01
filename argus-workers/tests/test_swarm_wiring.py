"""Tests for the specialist-swarm wiring in the Orchestrator.

Covers ``Orchestrator._run_swarm_specialists()`` — the gate that activates
the parallel IDOR/Auth/API specialist swarm at high/extreme aggressiveness.
"""

import logging
import sys
from unittest.mock import MagicMock, patch

import pytest

from models.recon_context import ReconContext

# ── Module-level mocks for OpenTelemetry (same pattern as test_orchestrator_*) ──
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
_otel_sdk = MagicMock()
_otel_sdk.resources = MagicMock()
_otel_sdk.trace = MagicMock()
_otel_sdk.trace.export = MagicMock()
_otel.exporter = _otel_exporter
_otel.sdk = _otel_sdk

_heavy_deps_patcher = patch.dict(
    sys.modules,
    {
        "opentelemetry": _otel,
        "opentelemetry.trace": _otel.trace,
        "opentelemetry.exporter": _otel_exporter,
        "opentelemetry.exporter.otlp": _otel_otlp,
        "opentelemetry.exporter.otlp.proto": _otel_proto,
        "opentelemetry.exporter.otlp.proto.http": _otel_http,
        "opentelemetry.exporter.otlp.proto.http.trace_exporter": _otel_http.trace_exporter,
        "opentelemetry.sdk": _otel_sdk,
        "opentelemetry.sdk.resources": _otel_sdk.resources,
        "opentelemetry.sdk.trace": _otel_sdk.trace,
        "opentelemetry.sdk.trace.export": _otel_sdk.trace.export,
    },
)
_heavy_deps_patcher.start()
from orchestrator_pkg.orchestrator import Orchestrator

_heavy_deps_patcher.stop()


@pytest.fixture(autouse=True)
def _mock_otel():
    with patch.dict(
        sys.modules,
        {
            "opentelemetry": _otel,
            "opentelemetry.trace": _otel.trace,
            "opentelemetry.exporter": _otel_exporter,
            "opentelemetry.exporter.otlp": _otel_otlp,
            "opentelemetry.exporter.otlp.proto": _otel_proto,
            "opentelemetry.exporter.otlp.proto.http": _otel_http,
            "opentelemetry.exporter.otlp.proto.http.trace_exporter": _otel_http.trace_exporter,
            "opentelemetry.sdk": _otel_sdk,
            "opentelemetry.sdk.resources": _otel_sdk.resources,
            "opentelemetry.sdk.trace": _otel_sdk.trace,
            "opentelemetry.sdk.trace.export": _otel_sdk.trace.export,
        }
    ):
        yield


def _orch(**overrides) -> Orchestrator:
    obj = object.__new__(Orchestrator)
    obj.engagement_id = "swarm-test-001"
    obj.tool_runner = MagicMock()
    obj.trace_id = None
    llm = MagicMock()
    llm.is_available.return_value = True
    obj.llm_client = llm
    obj.decision_repo = None
    obj.bug_bounty_mode = False

    from parsers.normalizer import FindingNormalizer

    obj.normalizer = FindingNormalizer()
    for k, v in overrides.items():
        setattr(obj, k, v)
    return obj


class TestSwarmMerge:
    def test_skips_duplicates_from_deterministic_pass(self):
        existing = [
            {"type": "BOLA", "endpoint": "https://example.com/api/1",
             "source_tool": "arjun"}
        ]
        swarm = [
            {"type": "BOLA", "endpoint": "https://example.com/api/1",
             "source_tool": "arjun"},
            {"type": "IDOR", "endpoint": "https://example.com/api/2",
             "source_tool": "web_scanner"},
        ]
        Orchestrator._merge_swarm_findings(existing, swarm)
        assert len(existing) == 2
        assert existing[1]["type"] == "IDOR"

    def test_keeps_distinct_findings(self):
        existing = []
        swarm = [
            {"type": "AUTH_BYPASS", "endpoint": "https://example.com/login",
             "source_tool": "jwt_tool"},
            {"type": "BOLA", "endpoint": "https://example.com/api/1",
             "source_tool": "arjun"},
        ]
        Orchestrator._merge_swarm_findings(existing, swarm)
        assert len(existing) == 2

    def test_empty_swarm_is_noop(self):
        existing = [{"type": "XSS", "endpoint": "e", "source_tool": "t"}]
        Orchestrator._merge_swarm_findings(existing, [])
        assert len(existing) == 1


class TestSwarmLocalTargets:
    def test_internal_target_opt_in_does_not_reach_specialist_target_filter(
        self, monkeypatch
    ):
        from agent.swarm import IDORAgent

        monkeypatch.setenv("ARGUS_ALLOW_INTERNAL_TARGETS", "1")
        rc = ReconContext(
            target_url="http://127.0.0.1:55693",
            live_endpoints=["http://127.0.0.1:55693/api/users"],
            has_api=True,
        )
        agent = IDORAgent(None, None, rc, "swarm-test-001")
        with patch("tools.scope_validator.validate_target_scope", return_value=True) as scope:
            assert agent.should_activate() is True
            assert agent._get_targets() == []
        scope.assert_not_called()


class TestSwarmRouting:
    @pytest.mark.parametrize("scan_mode", ["standard", "agent", "swarm"])
    def test_scan_modes_share_agent_first_path(self, scan_mode):
        orch = _orch()
        orch._check_timeout = MagicMock()
        orch.logger = MagicMock()
        orch._publish_scope = MagicMock()
        orch._run_scan_with_fallback = MagicMock(return_value=[])
        orch._maybe_run_browser_scanner = MagicMock()
        orch._save_findings = MagicMock(return_value=0)
        rc = ReconContext(target_url="https://example.com", has_api=True)
        job = {
            "targets": [rc.target_url],
            "recon_context": rc,
            "agent_mode": True,
            "scan_mode": scan_mode,
            "aggressiveness": "high",
            "scope": {"mode": "allowlist", "allowed_targets": [rc.target_url]},
        }
        with patch("orchestrator_pkg.custom_rules.CustomRulesService.publish"), patch(
            "orchestrator_pkg.planning.AdaptiveWorkflowPlanner"
        ) as planner, patch(
            "orchestrator_pkg.orchestrator.emit_thinking"
        ), patch("feature_flags.is_enabled", return_value=False):
            planner.return_value.build_plan.return_value = None
            planner.deduplicate_tools.return_value = None
            result = orch.run_scan(job)

        assert result["status"] == "completed"
        orch._run_scan_with_fallback.assert_called_once()
        assert orch._run_scan_with_fallback.call_args.args[3] == "high"


class TestSwarmGating:
    @pytest.mark.parametrize("aggressiveness", ["default", "moderate", "aggressive"])
    def test_skips_below_high_aggressiveness(self, aggressiveness):
        orch = _orch()
        with patch("agent.swarm.SwarmOrchestrator") as swarm_cls:
            assert orch._run_swarm_specialists(MagicMock(), aggressiveness) == []
        swarm_cls.assert_not_called()

    def test_skips_when_recon_context_missing(self):
        orch = _orch()
        assert orch._run_swarm_specialists(None, "extreme") == []

    def test_skips_when_llm_unavailable(self):
        llm = MagicMock()
        llm.is_available.return_value = False
        orch = _orch(llm_client=llm)
        assert orch._run_swarm_specialists(MagicMock(), "high") == []

    def test_skips_when_flag_disabled(self):
        orch = _orch()
        with patch("feature_flags.is_enabled", return_value=False) as ff:
            assert orch._run_swarm_specialists(MagicMock(), "extreme") == []
            ff.assert_called_once()

    def test_runs_swarm_and_normalizes_findings(self):
        orch = _orch()
        raw = [
            {"type": "BOLA", "severity": "HIGH", "endpoint": "https://example.com/api/1",
             "tool": "arjun", "evidence": {"request": "GET /api/1"}},
            {"type": "IDOR", "severity": "CRITICAL", "endpoint": "https://example.com/api/2",
             "tool": "web_scanner", "evidence": {}},
        ]
        fake_swarm = MagicMock()
        fake_swarm.run.return_value = (raw, {"arjun", "web_scanner"})

        with patch("feature_flags.is_enabled", return_value=True), patch(
            "agent.swarm.SwarmOrchestrator", return_value=fake_swarm
        ) as swarm_cls, patch(
            "llm_service.LLMService"
        ) as llm_svc_cls:
            result = orch._run_swarm_specialists(MagicMock(), "extreme")

        swarm_cls.assert_called_once()
        llm_svc_cls.assert_called_once()
        fake_swarm.run.assert_called_once()
        assert len(result) == 2
        assert result[0]["source_tool"] == "arjun"
        assert result[1]["source_tool"] == "web_scanner"

    def test_livefire_fixture_signals_activate_no_specialists(self, caplog):
        """Even raising the saved fixture run to high cannot supply missing signals."""
        orch = _orch()
        rc = ReconContext(
            target_url="http://127.0.0.1:55693",
            crawled_paths=["http://127.0.0.1:55693"],
        )
        with caplog.at_level(logging.INFO), patch(
            "feature_flags.is_enabled", return_value=True
        ), patch("llm_service.LLMService"), patch(
            "agent.swarm.emit_swarm_metrics"
        ) as metrics:
            result = orch._run_swarm_specialists(rc, "high")

        assert result == []
        orch.tool_runner.run.assert_not_called()
        assert "Swarm: no specialists activated" in caplog.text
        data = metrics.call_args.args[1]
        assert data["activated_agents"] == []
        assert {item["domain"] for item in data["inactive_agents"]} == {
            "idor", "auth", "api"
        }

    @pytest.mark.parametrize("aggressiveness", ["high", "extreme"])
    def test_real_swarm_activates_three_specialists_with_api_signals(
        self, aggressiveness
    ):
        """Exercise the real activation/parallel-dispatch path without running scanners."""
        orch = _orch()
        rc = ReconContext(
            target_url="https://example.com",
            has_api=True,
            api_endpoints=[
                "https://example.com/api/users", "https://example.com/api/orders"
            ],
        )
        with patch("feature_flags.is_enabled", return_value=True), patch(
            "llm_service.LLMService"
        ), patch("agent.swarm.IDORAgent.run", return_value=[]) as idor, patch(
            "agent.swarm.AuthAgent.run", return_value=[]
        ) as auth, patch("agent.swarm.APIAgent.run", return_value=[]) as api, patch(
            "agent.swarm.emit_swarm_agent_started"
        ), patch("agent.swarm.emit_swarm_agent_complete"), patch(
            "agent.swarm.emit_swarm_merge_complete"
        ), patch("agent.swarm.emit_swarm_metrics") as metrics:
            result = orch._run_swarm_specialists(rc, aggressiveness)

        assert result == []
        for specialist in (idor, auth, api):
            specialist.assert_called_once_with()
        assert set(metrics.call_args.args[1]["activated_agents"]) == {
            "idor", "auth", "api"
        }
        orch.tool_runner.run.assert_not_called()

    def test_swarm_failure_is_non_fatal(self):
        orch = _orch()
        with patch("feature_flags.is_enabled", return_value=True), patch(
            "agent.swarm.SwarmOrchestrator",
            side_effect=RuntimeError("swarm exploded"),
        ):
            assert orch._run_swarm_specialists(MagicMock(), "extreme") == []
