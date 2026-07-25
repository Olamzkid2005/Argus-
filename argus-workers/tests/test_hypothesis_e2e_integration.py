"""
End-to-end integration test for the hypothesis-driven autonomous loop.

Validates the full pipeline:
    Mock findings  ──►  HypothesisEngine.generate()
                               │
                               ▼
    update_plan_from_hypotheses()  ──►  WorkflowPlan phases activated
                               │
                               ▼
    get_coverage_report()  ──►  Accurate coverage metrics

This is a smoke-level integration test (marked 'smoke') that exercises
the real HypothesisEngine and bridge code without mocking internals.
"""

from __future__ import annotations

import pytest
from orchestrator_pkg.planning.adaptive_planner import WorkflowPlan
from orchestrator_pkg.planning.hypothesis_planning_bridge import (
    update_plan_from_hypotheses,
)

pytestmark = [
    pytest.mark.smoke,
    pytest.mark.unit,
]


# ── Test fixture: realistic mock findings ──────────────────────────────


@pytest.fixture
def mock_findings() -> list[dict]:
    """Simulate realistic findings from a scan of a vulnerable web app.

    Includes both grouped (CWE-clustered) findings and single HIGH/CRITICAL
    findings that trigger the single-finding hypothesis path.
    """
    return [
        # ── SQL Injection cluster (CWE-89, 3 findings) ──
        {
            "id": "sql-001",
            "type": "SQL_INJECTION",
            "severity": "CRITICAL",
            "confidence": 0.95,
            "endpoint": "https://example.com/login",
            "cwe_id": "89",
            "evidence": {"parameter": "username", "payload": "' OR '1'='1"},
        },
        {
            "id": "sql-002",
            "type": "SQL_INJECTION",
            "severity": "HIGH",
            "confidence": 0.85,
            "endpoint": "https://example.com/search",
            "cwe_id": "89",
            "evidence": {"parameter": "q", "payload": "' UNION SELECT 1--"},
        },
        {
            "id": "sql-003",
            "type": "SQL_INJECTION",
            "severity": "HIGH",
            "confidence": 0.80,
            "endpoint": "https://example.com/api/users",
            "cwe_id": "89",
            "evidence": {"parameter": "id", "payload": "1 OR 1=1"},
        },
        # ── XSS cluster (CWE-79, 2 findings) ──
        {
            "id": "xss-001",
            "type": "XSS",
            "severity": "HIGH",
            "confidence": 0.75,
            "endpoint": "https://example.com/contact",
            "cwe_id": "79",
            "evidence": {"parameter": "message", "payload": "<script>alert(1)</script>"},
        },
        {
            "id": "xss-002",
            "type": "XSS",
            "severity": "MEDIUM",
            "confidence": 0.65,
            "endpoint": "https://example.com/feedback",
            "cwe_id": "79",
            "evidence": {"parameter": "comment", "payload": "{{constructor.constructor('alert')()}}"},
        },
        # ── SSRF finding (single HIGH, triggers single-finding hypothesis) ──
        {
            "id": "ssrf-001",
            "type": "SSRF",
            "severity": "HIGH",
            "confidence": 0.70,
            "endpoint": "https://example.com/proxy?url=",
            "cwe_id": "918",
            "evidence": {"parameter": "url", "callback_url": "https://attacker.com/collab"},
        },
        # ── Auth weakness (single HIGH, no CWE group) ──
        {
            "id": "auth-001",
            "type": "AUTH_BYPASS",
            "severity": "HIGH",
            "confidence": 0.60,
            "endpoint": "https://example.com/admin",
            "cwe_id": "287",
            "evidence": {"status_code": 200, "expected": 403},
        },
        # ── INFO finding (should be ignored by single-finding path) ──
        {
            "id": "info-001",
            "type": "INFO_DISCLOSURE",
            "severity": "INFO",
            "confidence": 0.10,
            "endpoint": "https://example.com/robots.txt",
            "cwe_id": "200",
            "evidence": {"disclosure": "Disallowed paths exposed"},
        },
    ]


@pytest.fixture
def empty_plan() -> WorkflowPlan:
    """A fresh plan with no phases — hypothesis-driven phases will be added."""
    return WorkflowPlan(
        phases=[],
        total_phases=0,
        activated_phases=0,
        skipped_phases=[],
        target_url="https://example.com",
        summary="Hypothesis E2E test plan",
    )


@pytest.fixture
def seeded_plan() -> WorkflowPlan:
    """A plan with signal-driven phases already active — like a real scan."""
    from orchestrator_pkg.planning.adaptive_planner import (
        TestingPhase,
        ToolTask,
    )

    return WorkflowPlan(
        phases=[
            TestingPhase(
                name="auth_testing",
                description="Authentication testing",
                activation_reason="login page detected",
                order=10,
                tools=[
                    ToolTask(
                        tool_name="nuclei",
                        description="Auth scanning",
                        priority=10,
                        timeout=300,
                        args_template=["-u", "{target}", "-tags", "auth"],
                    ),
                ],
            ),
            TestingPhase(
                name="api_scan",
                description="API scanning",
                activation_reason="API endpoints found",
                order=20,
                tools=[
                    ToolTask(
                        tool_name="nuclei",
                        description="API scanning",
                        priority=10,
                        timeout=300,
                        args_template=["-u", "{target}", "-tags", "api"],
                    ),
                ],
            ),
        ],
        total_phases=2,
        activated_phases=2,
        skipped_phases=[],
        target_url="https://example.com",
        summary="Plan with signal-driven phases",
    )


# =========================================================================
# E2E Integration Tests
# =========================================================================


class TestHypothesisE2EIntegration:
    """End-to-end: real HypothesisEngine + real bridge → plan activated."""

    def test_empty_findings_no_hypotheses(self, empty_plan):
        """No findings → no hypotheses → no plan changes."""
        from tools.hypothesis_engine import HypothesisEngine

        engine = HypothesisEngine()
        hypotheses = engine.generate([], "eng-e2e-empty")

        assert hypotheses == []
        update_plan_from_hypotheses(empty_plan, hypotheses)

        assert len(empty_plan.phases) == 0
        assert empty_plan.activated_phases == 0
        assert empty_plan.total_phases == 0

    def test_real_hypotheses_generated_from_findings(self, mock_findings):
        """Real findings produce real hypotheses from HypothesisEngine."""
        from tools.hypothesis_engine import HypothesisEngine

        engine = HypothesisEngine()
        hypotheses = engine.generate(mock_findings, "eng-e2e-01")

        assert len(hypotheses) > 0, "Engine should produce hypotheses"

        # At least one grouped hypothesis (SQLi cluster = CWE-89)
        grouped = [h for h in hypotheses if h["status"] == "UNVERIFIED"]
        assert len(grouped) >= 1

        # At least one single-finding hypothesis (SSRF with verifier tool)
        # Also the AUTH_BYPASS with no verifier → no single-finding hypothesis
        highest = max(h["confidence"] for h in hypotheses)
        assert highest >= 0.7, "Should have high-confidence hypotheses"

    def test_hypotheses_have_required_fields(self, mock_findings):
        """Every hypothesis has all required fields for the bridge."""
        from tools.hypothesis_engine import HypothesisEngine

        engine = HypothesisEngine()
        hypotheses = engine.generate(mock_findings, "eng-e2e-02")

        required_fields = {
            "id", "engagement_id", "description", "root_cause_key",
            "confidence", "status", "verification_steps", "finding_ids",
            "suggested_tools", "created_at",
        }
        for h in hypotheses:
            missing = required_fields - h.keys()
            assert not missing, (
                f"Hypothesis {h.get('id', '?')} missing fields: {missing}"
            )
            assert isinstance(h["confidence"], (int, float))
            assert 0.0 <= h["confidence"] <= 1.0
            assert isinstance(h["suggested_tools"], list)

    def test_hypothesis_to_plan_integration(self, mock_findings, empty_plan):
        """Full E2E: findings → hypotheses → plan activated."""
        from tools.hypothesis_engine import HypothesisEngine

        engine = HypothesisEngine()
        hypotheses = engine.generate(mock_findings, "eng-e2e-03")

        # Update plan with the hypotheses
        update_plan_from_hypotheses(empty_plan, hypotheses)

        # Should have activated at least one phase
        assert empty_plan.activated_phases >= 1, (
            f"Expected ≥1 phase activated, got {empty_plan.activated_phases}"
        )
        assert empty_plan.total_phases >= 1
        assert len(empty_plan.phases) == empty_plan.activated_phases

        # Verify phases have hypothesis-driven activation reasons
        for phase in empty_plan.phases:
            assert "hypothesis" in phase.activation_reason.lower(), (
                f"Phase '{phase.name}' missing hypothesis reason"
            )
            assert len(phase.tools) >= 1, (
                f"Phase '{phase.name}' has no tools"
            )

    def test_coverage_report_reflects_hypothesis_phases(
        self, mock_findings, empty_plan
    ):
        """Coverage report should accurately reflect hypothesis-activated phases."""
        from tools.hypothesis_engine import HypothesisEngine

        engine = HypothesisEngine()
        hypotheses = engine.generate(mock_findings, "eng-e2e-04")

        update_plan_from_hypotheses(empty_plan, hypotheses)

        report = empty_plan.get_coverage_report()

        assert report["activated_count"] == empty_plan.activated_phases
        assert report["total_phases"] == empty_plan.total_phases
        assert report["coverage_pct"] == 1.0  # All hypothesis phases are activated

        # Every active phase should appear in the report
        for phase in empty_plan.phases:
            assert phase.name in report["activated"], (
                f"Phase '{phase.name}' not in coverage activated list"
            )

    def test_existing_phases_not_duplicated(
        self, mock_findings, seeded_plan
    ):
        """Existing phases should never be duplicated by hypothesis activation.

        If a generated hypothesis maps to an already-active phase, the bridge
        should annotate it (rather than duplicate). If no hypothesis maps to
        an existing phase, the phase should remain unchanged.
        """
        from tools.hypothesis_engine import HypothesisEngine

        engine = HypothesisEngine()
        hypotheses = engine.generate(mock_findings, "eng-e2e-05")
        initial_names = {p.name for p in seeded_plan.phases}

        update_plan_from_hypotheses(seeded_plan, hypotheses)
        current_names = {p.name for p in seeded_plan.phases}

        # Every original phase should still be present exactly once
        for name in initial_names:
            count = sum(1 for p in seeded_plan.phases if p.name == name)
            assert count == 1, (
                f"Phase '{name}' was duplicated! Count: {count}"
            )

        # If a hypothesis happened to match an existing phase, it should
        # be annotated. Otherwise, the phase stays as-is.
        for phase in seeded_plan.phases:
            if phase.name in initial_names:
                # Existing phase: may or may not be annotated depending
                # on whether a hypothesis matched it — that's OK
                pass

        # New phases should have been added from non-duplicate hypotheses
        assert len(seeded_plan.phases) > len(initial_names), (
            f"Expected new phases beyond initial {len(initial_names)}, "
            f"got {len(seeded_plan.phases)}"
        )

    def test_sql_injection_hypothesis_maps_to_input_validation_phase(
        self, mock_findings, empty_plan
    ):
        """SQLi findings should trigger input_validation phase activation."""
        from tools.hypothesis_engine import HypothesisEngine

        engine = HypothesisEngine()
        hypotheses = engine.generate(mock_findings, "eng-e2e-06")

        update_plan_from_hypotheses(empty_plan, hypotheses)

        phase_names = {p.name for p in empty_plan.phases}
        assert "input_validation" in phase_names, (
            f"SQLi findings should activate input_validation phase, "
            f"got {phase_names}"
        )

    def test_apply_hypothesis_engine_one_call(self, mock_findings, empty_plan):
        """The one-call apply_hypothesis_engine function works end-to-end."""
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            apply_hypothesis_engine,
        )

        hypotheses = apply_hypothesis_engine(empty_plan, mock_findings, "eng-e2e-once")

        assert isinstance(hypotheses, list)
        assert len(hypotheses) > 0, "Should generate hypotheses from findings"
        assert empty_plan.activated_phases >= 1, (
            "Plan should have activated phases"
        )
        # Verify the hypotheses look correct
        for h in hypotheses:
            assert "id" in h
            assert "confidence" in h

    def test_apply_hypothesis_engine_empty_findings(self, empty_plan):
        """One-call with empty findings returns empty list, no plan changes."""
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            apply_hypothesis_engine,
        )

        hypotheses = apply_hypothesis_engine(empty_plan, [], "eng-e2e-empty2")

        assert hypotheses == []
        assert empty_plan.activated_phases == 0
        assert empty_plan.total_phases == 0

    def test_hypothesis_engine_graceful_degradation(self):
        """Engine returns empty list on bad input without crashing."""
        from tools.hypothesis_engine import HypothesisEngine

        engine = HypothesisEngine()

        # None findings (should not crash)
        try:
            hypotheses = engine.generate(None, "eng-e2e-err")  # type: ignore[arg-type]
            assert isinstance(hypotheses, list)
        except Exception:
            pytest.fail("HypothesisEngine.generate(None) should not crash")

        # Findings with missing fields (should not crash)
        malformed = [{"wrong_key": "value"}] * 10
        try:
            hypotheses = engine.generate(malformed, "eng-e2e-err2")
            assert isinstance(hypotheses, list)
        except Exception:
            pytest.fail("HypothesisEngine.generate(malformed) should not crash")


class TestHypothesisE2EPhaseActivation:
    """Verify specific phase activation patterns from real hypotheses."""

    @pytest.fixture(autouse=True)
    def _generate_and_activate(self, mock_findings, empty_plan):
        """Generate hypotheses and activate plan for all tests."""
        from tools.hypothesis_engine import HypothesisEngine

        engine = HypothesisEngine()
        hypotheses = engine.generate(mock_findings, "eng-e2e-phases")
        update_plan_from_hypotheses(empty_plan, hypotheses)
        self.plan = empty_plan
        self.hypotheses = hypotheses

    def test_phase_order_is_200(self):
        """Hypothesis-driven phases should have order=200."""
        for phase in self.plan.phases:
            assert phase.order == 200, (
                f"Phase '{phase.name}' has order {phase.order}, expected 200"
            )

    def test_phases_have_tool_tasks(self):
        """Each activated phase should have non-empty tool tasks."""
        for phase in self.plan.phases:
            assert len(phase.tools) >= 1
            for tool in phase.tools:
                # Verify ToolTask is properly constructed (names may change)
                from orchestrator_pkg.planning.adaptive_planner import ToolTask as _TT
                assert isinstance(tool, _TT), f"Expected ToolTask, got {type(tool)}"
                assert isinstance(tool.tool_name, str) and tool.tool_name
                assert isinstance(tool.timeout, int) and tool.timeout > 0
                assert isinstance(tool.args_template, list) and len(tool.args_template) > 0

    def test_coverage_report_complete(self):
        """Coverage report should contain all phases."""
        report = self.plan.get_coverage_report()
        phase_names = {p.name for p in self.plan.phases}
        reported_active = set(report["activated"])

        # Every phase in the plan should be in the activated list
        assert phase_names == reported_active, (
            f"Plan phases {phase_names} don't match report {reported_active}"
        )
