"""Tests for TestFormatting from adaptive_planner."""


from orchestrator_pkg.planning.adaptive_planner import (
    AdaptiveWorkflowPlanner,
    WorkflowPlan,
)

from .conftest import _make_mock_recon


class TestFormatting:
    """Test plan formatting and summary methods."""

    def test_format_plan_for_agent(self):
        """format_plan_for_agent returns a non-empty string with plan details."""
        rc = _make_mock_recon(
            has_login_page=True,
            tech_stack=["WordPress"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        formatted = planner.format_plan_for_agent(plan)
        assert "=== ADAPTIVE TESTING PLAN ===" in formatted
        assert "=== END TESTING PLAN ===" in formatted
        assert "Phase 1:" in formatted
        assert "nuclei" in formatted.lower()

    def test_format_empty_plan(self):
        """Empty plans produce empty format output."""
        planner = AdaptiveWorkflowPlanner()
        formatted = planner.format_plan_for_agent(WorkflowPlan())
        assert formatted == ""

    def test_get_plan_summary(self):
        """get_plan_summary returns a serializable dict."""
        rc = _make_mock_recon(has_login_page=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        summary = planner.get_plan_summary(plan)
        assert isinstance(summary, dict)
        assert "phases" in summary
        assert "activated_phases" in summary
        assert "skipped" in summary


# ── Dynamic Phase Chaining Tests ───────────────────────────────────────
