"""Tests for TestToolArgsResolution from adaptive_planner."""


from orchestrator_pkg.planning.adaptive_planner import (
    AdaptiveWorkflowPlanner,
    ToolTask,
)


class TestToolArgsResolution:
    """Test that tool argument templates are resolved correctly."""

    def test_basic_resolution(self):
        """Placeholder strings are replaced with actual values."""
        task = ToolTask(
            tool_name="nuclei",
            description="test",
            args_template=["-u", "{target}", "-jsonl", "-silent"],
        )
        resolved = AdaptiveWorkflowPlanner.resolve_tool_args(task, "https://example.com", "eng-123")
        assert resolved == ["-u", "https://example.com", "-jsonl", "-silent"]

    def test_multiple_placeholders(self):
        """Multiple different placeholders are resolved."""
        task = ToolTask(
            tool_name="test_tool",
            args_template=["{target}", "{engagement_id}", "{targets}"],
        )
        resolved = AdaptiveWorkflowPlanner.resolve_tool_args(task, "https://target.com", "eng-001")
        assert resolved == ["https://target.com", "eng-001", "https://target.com"]

    def test_no_placeholders(self):
        """Args without placeholders pass through unchanged."""
        task = ToolTask(tool_name="test_tool", args_template=["--batch", "--json"])
        resolved = AdaptiveWorkflowPlanner.resolve_tool_args(task, "https://x.com", "eng-1")
        assert resolved == ["--batch", "--json"]


# ── Formatting Tests ───────────────────────────────────────────────────
