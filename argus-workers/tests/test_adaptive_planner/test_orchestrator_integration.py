"""Tests for TestOrchestratorIntegration from adaptive_planner."""

from types import SimpleNamespace

from orchestrator_pkg.planning.adaptive_planner import (
    AdaptiveWorkflowPlanner,
    TestingPhase,
    ToolTask,
    WorkflowPlan,
)

from .conftest import _make_mock_recon


class TestOrchestratorIntegration:
    """Test that the planner integrates correctly with Orchestrator patterns."""

    def test_plan_as_agent_context(self):
        """The plan can be formatted as context for the LLM agent."""
        rc = _make_mock_recon(
            has_login_page=True,
            tech_stack=["WordPress"],
            parameter_bearing_urls=["/page?id=1"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        formatted = planner.format_plan_for_agent(plan)

        # The formatted plan should mention key information
        assert "auth_testing" in formatted
        assert "tech_deep_scan" in formatted

    def test_plan_summary_for_metrics(self):
        """Plan summary is serializable for observability and metrics."""
        rc = _make_mock_recon(has_login_page=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        summary = planner.get_plan_summary(plan)
        import json
        serialized = json.dumps(summary)
        assert serialized  # Must be valid JSON
        assert "auth_testing" in serialized
