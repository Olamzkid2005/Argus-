"""Tests for the specialist-swarm wiring in the Orchestrator.

Covers ``Orchestrator._run_swarm_specialists()`` — the gate that activates
the parallel IDOR/Auth/API specialist swarm at high/extreme aggressiveness.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

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


class TestSwarmGating:
    def test_skips_below_high_aggressiveness(self):
        orch = _orch()
        assert orch._run_swarm_specialists(MagicMock(), "default") == []

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

    def test_swarm_failure_is_non_fatal(self):
        orch = _orch()
        with patch("feature_flags.is_enabled", return_value=True), patch(
            "agent.swarm.SwarmOrchestrator",
            side_effect=RuntimeError("swarm exploded"),
        ):
            assert orch._run_swarm_specialists(MagicMock(), "extreme") == []
