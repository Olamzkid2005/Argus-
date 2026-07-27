"""Tests for TestToolDedup from adaptive_planner."""

from types import SimpleNamespace

from orchestrator_pkg.planning.adaptive_planner import (
    AdaptiveWorkflowPlanner,
    TestingPhase,
    ToolTask,
    WorkflowPlan,
)

from .conftest import _make_mock_recon


class TestToolDedup:
    """Test that duplicate tool+tag combinations are removed."""

    def test_dedup_same_tool_and_tags(self):
        """Same tool with same tags in different phases gets deduped."""
        phase1 = TestingPhase(
            name="auth_testing",
            order=20,
            tools=[
                ToolTask(tool_name="nuclei", args_template=["-tags", "auth,login"]),
            ],
        )
        phase2 = TestingPhase(
            name="tech_deep_scan",
            order=10,
            tools=[
                ToolTask(tool_name="nuclei", args_template=["-tags", "auth,login"]),
            ],
        )
        plan = WorkflowPlan(phases=[phase1, phase2])
        deduped = AdaptiveWorkflowPlanner.deduplicate_tools(plan)
        total_tools = sum(len(p.tools) for p in deduped.phases)
        assert total_tools == 1, f"Expected 1 tool total, got {total_tools}"

    def test_dedup_different_tools_preserved(self):
        """Different tools or tags are not removed by dedup."""
        phase1 = TestingPhase(
            name="auth_testing",
            order=20,
            tools=[
                ToolTask(tool_name="nuclei", args_template=["-tags", "auth,login"]),
            ],
        )
        phase2 = TestingPhase(
            name="input_validation",
            order=60,
            tools=[
                ToolTask(tool_name="dalfox", args_template=["url", "{target}", "--json"]),
            ],
        )
        plan = WorkflowPlan(phases=[phase1, phase2])
        deduped = AdaptiveWorkflowPlanner.deduplicate_tools(plan)
        total_tools = sum(len(p.tools) for p in deduped.phases)
        assert total_tools == 2, f"Expected 2 tools total, got {total_tools}"


# ── Orchestrator Integration Tests ─────────────────────────────────────
