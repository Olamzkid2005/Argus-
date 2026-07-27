"""Tests for TestDynamicChaining from adaptive_planner."""

from types import SimpleNamespace

from orchestrator_pkg.planning.adaptive_planner import (
    AdaptiveWorkflowPlanner,
    TestingPhase,
    ToolTask,
    WorkflowPlan,
)

from .conftest import _make_mock_recon


class TestDynamicChaining:
    """Test that findings from completed phases trigger follow-up phases."""

    def test_no_findings_no_trigger(self):
        """No findings means no trigger phases are added."""
        planner = AdaptiveWorkflowPlanner()
        phase = TestingPhase(
            name="auth_testing",
            order=20,
            triggers=["session_analysis"],
        )
        plan = WorkflowPlan(phases=[phase])
        updated = planner.update_plan_from_results(plan, "auth_testing", [])
        assert len(updated.phases) == 1  # Only auth_testing remains

    def test_unknown_phase_no_trigger(self):
        """Completing an unknown phase does not trigger anything."""
        planner = AdaptiveWorkflowPlanner()
        plan = WorkflowPlan(phases=[])
        updated = planner.update_plan_from_results(
            plan, "nonexistent", [{"type": "FAKE"}]
        )
        assert len(updated.phases) == 0

    def test_no_triggers_no_change(self):
        """A phase without triggers does not activate anything new."""
        planner = AdaptiveWorkflowPlanner()
        phase = TestingPhase(name="infrastructure_scan", order=70, triggers=[])
        plan = WorkflowPlan(phases=[phase])
        updated = planner.update_plan_from_results(
            plan, "infrastructure_scan", [{"type": "OPEN_PORT"}]
        )
        assert len(updated.phases) == 1


# ── GraphQL Introspection Tests ─────────────────────────────────────────────
