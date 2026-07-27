"""Tests for TestPhaseOrdering from adaptive_planner."""

from types import SimpleNamespace

from orchestrator_pkg.planning.adaptive_planner import (
    AdaptiveWorkflowPlanner,
    TestingPhase,
    ToolTask,
    WorkflowPlan,
)

from .conftest import _make_mock_recon


class TestPhaseOrdering:
    """Test that phases are ordered correctly with dependency resolution."""

    def test_dependencies_ordered_first(self):
        """Dependencies appear before dependents."""
        rc = _make_mock_recon(
            has_login_page=True,
            auth_endpoints=["/login"],
            has_api=True,
            api_endpoints=["/api/v1"],
            tech_stack=["WordPress"],
            parameter_bearing_urls=["/page?q=1"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        names = [p.name for p in plan.phases]
        # tech_deep_scan has order 10, should come before auth_testing (order 20)
        assert names.index("tech_deep_scan") < names.index("auth_testing"), (
            f"tech_deep_scan should come before auth_testing: {names}"
        )
        # auth_testing should come before access_control (depends_on auth_testing)
        assert names.index("auth_testing") < names.index("access_control"), (
            f"auth_testing should come before access_control: {names}"
        )

    def test_phase_has_tools_when_activated(self):
        """Activated phases have tool tasks generated."""
        rc = _make_mock_recon(
            has_login_page=True,
            tech_stack=["WordPress"],
            parameter_bearing_urls=["/page?id=1"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        for phase in plan.phases:
            assert len(phase.tools) > 0, (
                f"Phase '{phase.name}' has no tools"
            )
            for task in phase.tools:
                assert isinstance(task, ToolTask)
                assert task.tool_name


# ── Tool Args Resolution Tests ─────────────────────────────────────────
