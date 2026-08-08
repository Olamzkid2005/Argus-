"""
Tests for orchestrator verification dispatch logic — Gap 1.1 & Gap 5.1.

Covers:
  - Orchestrator.run_verification() — the actual verification recommendation method
  - Auto-verification dispatch inside run_scan() (Gap 1.1)
  - Foothold / post-exploitation check inside run_analysis() (Gap 5.1)
"""

from __future__ import annotations

import sys
import time
from unittest.mock import MagicMock, patch

import pytest

# ── Module-level mocks for OpenTelemetry ──
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

_heavy_deps_patcher = patch.dict(
    sys.modules,
    {
        "opentelemetry": _otel, "opentelemetry.trace": _otel.trace,
        "opentelemetry.exporter": _otel_exporter, "opentelemetry.exporter.otlp": _otel_otlp,
        "opentelemetry.exporter.otlp.proto": _otel_proto,
        "opentelemetry.exporter.otlp.proto.http": _otel_http,
        "opentelemetry.exporter.otlp.proto.http.trace_exporter": _otel_http.trace_exporter,
        "opentelemetry.sdk": _otel_sdk, "opentelemetry.sdk.resources": _otel_sdk.resources,
        "opentelemetry.sdk.trace": _otel_sdk.trace,
        "opentelemetry.sdk.trace.export": _otel_sdk.trace.export,
    },
)
_heavy_deps_patcher.start()
from orchestrator_pkg.orchestrator import Orchestrator

_heavy_deps_patcher.stop()


def _finding(fid: str, severity: int) -> dict:
    return {"id": fid, "severity": severity, "type": "XSS", "endpoint": "https://example.com"}

SEVERITY_HIGH = 3
SEVERITY_CRITICAL = 4
SEVERITY_MEDIUM = 2


@pytest.fixture(autouse=True)
def _mock_otel():
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


# ── run_verification() tests ─────────────────────────────────────────


class TestRunVerification:
    """Tests for Orchestrator.run_verification()."""

    @pytest.fixture
    def orch(self):
        obj = object.__new__(Orchestrator)
        obj.engagement_id = "test-eng-001"
        obj.ws_publisher = MagicMock()
        obj.trace_id = None
        return obj

    def test_skips_when_no_findings(self, orch):
        result = Orchestrator.run_verification(orch, {"findings": []})
        assert result["status"] == "skipped"
        assert result["findings_to_verify"] == 0
        orch.ws_publisher.publish_scanner_activity.assert_not_called()

    def test_skips_when_all_below_threshold(self, orch):
        result = Orchestrator.run_verification(orch, {
            "findings": [_finding("f1", SEVERITY_MEDIUM), _finding("f2", 1)],
            "threshold": SEVERITY_HIGH,
        })
        assert result["status"] == "no_candidates"
        assert result["findings_to_verify"] == 0
        assert result["findings_verified"] == 0

    def test_marks_high_and_critical(self, orch):
        """HIGH/CRITICAL candidates are selected and verified."""

        async def _vfy(finding, engagement_id=""):
            return {
                "id": finding.get("id"),
                "type": "xss",
                "endpoint": finding.get("endpoint", ""),
                "verification": {"verified": True},
            }

        findings = [_finding("f1", SEVERITY_HIGH), _finding("f2", SEVERITY_CRITICAL)]
        with patch("tools.finding_verifier.verify_finding") as mock_vfy:
            mock_vfy.side_effect = _vfy
            result = Orchestrator.run_verification(orch, {"findings": findings, "threshold": SEVERITY_HIGH, "max_to_verify": 10})
        assert result["findings_to_verify"] == 2
        assert result["findings_verified"] == 2
        assert set(result["verified_ids"]) == {"f1", "f2"}
        assert findings[0].get("_verified") is True
        assert findings[1]["verification"]["verified"] is True

    def test_respects_max_to_verify(self, orch):
        """Only max_to_verify findings are selected."""

        async def _vfy(finding, engagement_id=""):
            return {
                "id": finding.get("id"),
                "type": "xss",
                "endpoint": finding.get("endpoint", ""),
                "verification": {"verified": True},
            }

        findings = [_finding(f"f{i}", SEVERITY_CRITICAL) for i in range(5)]
        with patch("tools.finding_verifier.verify_finding") as mock_vfy:
            mock_vfy.side_effect = _vfy
            result = Orchestrator.run_verification(orch, {"findings": findings, "threshold": SEVERITY_HIGH, "max_to_verify": 2})
        assert result["findings_to_verify"] == 2
        assert len(result["verified_ids"]) == 2

    def test_sorts_by_severity_descending(self, orch):
        """Most severe findings are verified first."""

        async def _vfy(finding, engagement_id=""):
            return {
                "id": finding.get("id"),
                "type": "xss",
                "endpoint": finding.get("endpoint", ""),
                "verification": {"verified": True},
            }

        findings = [_finding("f2", SEVERITY_MEDIUM), _finding("f3", SEVERITY_HIGH), _finding("f1", SEVERITY_CRITICAL)]
        with patch("tools.finding_verifier.verify_finding") as mock_vfy:
            mock_vfy.side_effect = _vfy
            result = Orchestrator.run_verification(orch, {"findings": findings, "threshold": SEVERITY_MEDIUM, "max_to_verify": 2})
        assert result["findings_to_verify"] == 2
        # Top 2 by severity: f1 (critical), f3 (high) — f2 (medium) excluded
        assert result["verified_ids"] == ["f1", "f3"]

    def test_emits_scanner_activity_event(self, orch):
        """A verification_complete SSE event is emitted with verified findings."""

        async def _vfy(finding, engagement_id=""):
            return {
                "id": finding.get("id"),
                "type": "xss",
                "endpoint": finding.get("endpoint", ""),
                "verification": {"verified": True},
            }

        from streaming import EventType

        findings = [_finding("f1", SEVERITY_CRITICAL), _finding("f2", SEVERITY_HIGH)]
        with (
            patch("tools.finding_verifier.verify_finding") as mock_vfy,
            patch("streaming.emit_event") as mock_event,
        ):
            mock_vfy.side_effect = _vfy
            Orchestrator.run_verification(orch, {"findings": findings, "threshold": SEVERITY_HIGH, "max_to_verify": 5, "phase": "scan"})
        activity_calls = [
            c for c in mock_event.call_args_list if c.args[1] == EventType.SCANNER_ACTIVITY
        ]
        assert len(activity_calls) == 1
        data = activity_calls[0].args[2]
        assert data["activity"] == "verification_complete"
        assert set(data["finding_ids"]) == {"f1", "f2"}
        assert data["total_candidates"] == 2
        assert data["http_verified"] == 2

    def test_verification_priority_set(self, orch):
        """Verified findings carry verification metadata on the finding dict."""

        async def _vfy(finding, engagement_id=""):
            return {
                "id": finding.get("id"),
                "type": "xss",
                "endpoint": finding.get("endpoint", ""),
                "verification": {"verified": True},
            }

        findings = [_finding("f_crit", SEVERITY_CRITICAL), _finding("f_high", SEVERITY_HIGH)]
        with patch("tools.finding_verifier.verify_finding") as mock_vfy:
            mock_vfy.side_effect = _vfy
            Orchestrator.run_verification(orch, {"findings": findings, "threshold": SEVERITY_HIGH, "max_to_verify": 10})
        assert findings[0].get("_verified") is True
        assert findings[1]["verification"]["verified"] is True

    def test_returns_correct_result_structure(self, orch):
        """Result dict follows the run_verification contract."""

        async def _vfy(finding, engagement_id=""):
            return {
                "id": finding.get("id"),
                "type": "xss",
                "endpoint": finding.get("endpoint", ""),
                "verification": {"verified": True},
            }

        with patch("tools.finding_verifier.verify_finding") as mock_vfy:
            mock_vfy.side_effect = _vfy
            result = Orchestrator.run_verification(orch, {"findings": [_finding("f1", SEVERITY_CRITICAL)], "threshold": SEVERITY_HIGH, "max_to_verify": 10, "phase": "scan"})
        assert result["phase"] == "verification"
        assert result["status"] == "completed"
        assert result["findings_to_verify"] == 1
        assert result["verified_ids"] == ["f1"]


# ── Auto-verification in run_scan() tests (Gap 1.1) ──────────────────


class TestAutoVerificationInRunScan:
    """Tests for auto-verification dispatch in Orchestrator.run_scan()."""

    def _make(self):
        o = object.__new__(Orchestrator)
        o.engagement_id = "test-eng-001"
        o.start_time = time.time()
        o.ws_publisher = MagicMock()
        o.logger = MagicMock()
        o.state = None
        o._check_timeout = MagicMock()
        o._save_findings = MagicMock(return_value=0)
        o._maybe_run_browser_scanner = MagicMock(return_value=[])
        o.bug_bounty_mode = False
        o.llm_client = MagicMock()
        o.llm_payload_generator = None
        o.mcp = MagicMock()
        o.trace_id = None
        o.span_recorder = MagicMock()
        o.span_recorder.span.return_value.__enter__ = MagicMock(return_value=None)
        o.span_recorder.span.return_value.__exit__ = MagicMock(return_value=None)
        o._execution_engine = None
        o.tool_runner = MagicMock()
        o.parser = MagicMock()
        o.normalizer = MagicMock()
        return o

    def _job(self, findings):
        return {
            "type": "scan", "targets": ["https://example.com"],
            "budget": {}, "recon_context": MagicMock(),
            "scan_mode": "deterministic",  # bypass agent path
            "findings": findings,
        }

    def _run_scan(self, orch, job, findings, vfy_side_effect=None):
        """Helper: runs run_scan with all standard patches and returns result + vfy mock."""
        mock_vfy = MagicMock()
        if vfy_side_effect:
            mock_vfy.side_effect = vfy_side_effect
        orch.run_verification = mock_vfy
        # Patch at the SOURCE module — execute_scan_pipeline does a local import
        # of execute_scan_tools from orchestrator_pkg.scan INSIDE its body.
        # Also need to handle the case where execute_scan_pipeline isn't reached
        # due to scope filtering earlier in the chain, so also patch the scan module.
        with patch("orchestrator_pkg.scan.execute_scan_tools", return_value=findings):
            with patch("orchestrator_pkg.custom_rules.CustomRulesService"):
                with patch("feature_flags.is_enabled", return_value=False):
                    with patch("orchestrator_pkg.orchestrator.ScanLogger"):
                        with patch("streaming.emit_thinking"):
                            result = Orchestrator.run_scan(orch, job)
        return result, mock_vfy

    def test_calls_run_verification_when_findings_exist(self):
        orch = self._make()
        result, mock_vfy = self._run_scan(orch, self._job([]), [{"id": "f1", "severity": 3}])
        assert result["status"] == "completed"
        mock_vfy.assert_called_once()
        kw = mock_vfy.call_args[0][0]
        assert kw["threshold"] == 3 and kw["max_to_verify"] == 10 and kw["phase"] == "scan"

    def test_skips_verification_when_no_findings(self):
        orch = self._make()
        result, mock_vfy = self._run_scan(orch, self._job([]), [])
        assert result["status"] == "completed"
        mock_vfy.assert_not_called()

    def test_verification_failure_does_not_crash_scan(self):
        orch = self._make()
        result, mock_vfy = self._run_scan(
            orch, self._job([]), [{"id": "f1", "severity": 3}],
            vfy_side_effect=RuntimeError("verification failed"),
        )
        assert result["status"] == "completed"
        assert mock_vfy.call_count == 1


# ── Foothold check in run_analysis() tests (Gap 5.1) ─────────────────


class TestFootholdCheckInRunAnalysis:
    """Tests for post-exploitation foothold check in Orchestrator.run_analysis()."""

    def _make(self):
        o = object.__new__(Orchestrator)
        o.engagement_id = "test-eng-001"
        o.start_time = time.time()
        o.ws_publisher = MagicMock()
        o.logger = MagicMock()
        o._check_timeout = MagicMock()
        o.llm_client = MagicMock()
        o.llm_payload_generator = None
        o.bug_bounty_mode = False
        o.state = None
        o.trace_id = None
        o.span_recorder = MagicMock()
        o.span_recorder.span.return_value.__enter__ = MagicMock(return_value=None)
        o.span_recorder.span.return_value.__exit__ = MagicMock(return_value=None)
        o._get_org_id = MagicMock(return_value="org-1")
        o._load_priority_vuln_classes = MagicMock(return_value=[])
        o.normalizer = MagicMock()
        o.finding_repo = MagicMock()
        o.engagement_repo = MagicMock()
        o.rate_limit_repo = MagicMock()
        o.mcp = MagicMock()
        return o

    def _run(self, orch, scored, pe_side_effect=None):
        with patch("orchestrator_pkg.analysis.SnapshotService") as ss:
            ss.return_value.load_and_build.return_value = ({}, MagicMock(), [], "org-1")
            with patch("orchestrator_pkg.analysis.IntelligenceService") as isvc:
                inst = MagicMock()
                inst.evaluate.return_value = {"scored_findings": scored, "analysis": {"risk_level": "high", "coverage_gaps": [], "high_value_targets": []}, "reasoning": ""}
                inst.run_synthesis.return_value = ({}, None, None, None, [])
                isvc.return_value = inst
                with patch("orchestrator_pkg.analysis.LlmBatchService"):
                    with patch("orchestrator_pkg.analysis.BudgetPersistenceService"):
                        with patch("orchestrator_pkg.persistence.FindingPersistenceService"):
                            with patch("tools.post_exploitation.PostExploitationOrchestrator") as pe:
                                if pe_side_effect:
                                    pe.side_effect = pe_side_effect
                                else:
                                    pe_inst = MagicMock()
                                    pe_inst.has_foothold_findings.return_value = any(f.get("severity", 0) >= 4 for f in scored)
                                    pe.return_value = pe_inst
                                with patch("orchestrator_pkg.orchestrator.ScanLogger"):
                                    with patch("orchestrator_pkg.orchestrator.os.getenv", return_value="pg://test:test@localhost/test"):
                                        return Orchestrator.run_analysis(orch, {"type": "analyze", "engagement_id": "test-eng-001", "budget": {}})

    @patch("streaming.emit_thinking")
    @patch("feature_flags.is_enabled")
    def test_sets_flag_when_foothold_detected(self, ff, emit):
        ff.return_value = False
        result = self._run(self._make(), [{"id": "f1", "type": "RCE", "severity": 4}])
        assert result["needs_post_exploitation"] is True and result["status"] == "completed"

    @patch("streaming.emit_thinking")
    @patch("feature_flags.is_enabled")
    def test_sets_flag_false_when_no_foothold(self, ff, emit):
        ff.return_value = False
        result = self._run(self._make(), [])
        assert result["needs_post_exploitation"] is False and result["status"] == "completed"

    @patch("streaming.emit_thinking")
    @patch("feature_flags.is_enabled")
    def test_graceful_degradation_when_post_exploit_fails(self, ff, emit):
        ff.return_value = False
        result = self._run(self._make(), [{"id": "f1", "type": "RCE", "severity": 4}], pe_side_effect=Exception("unavailable"))
        assert result["needs_post_exploitation"] is False and result["status"] == "completed"
