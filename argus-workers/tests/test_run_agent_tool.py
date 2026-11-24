"""Tests for tools.run_agent_tool — Category: function"""

import pytest

from tools.run_agent_tool import main, resolve_tool_class


class TestResolveToolClass:
    """Tests for the resolve_tool_class function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            resolve_tool_class()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            resolve_tool_class()


class TestMain:
    """Tests for the main function."""

    def test_basic_execution(self):
        """Function requires arguments (raises SystemExit)."""
        with pytest.raises(SystemExit):
            main()

    def test_returns_correct_type(self):
        """Function requires arguments (raises SystemExit)."""
        with pytest.raises(SystemExit):
            main()

    def test_stamps_the_claimed_intent_goal_on_findings(self, monkeypatch, capsys):
        """The intent worker's tool run attributes its findings to the goal."""
        import json

        from tool_core.base import AbstractTool
        from tool_core.result import ToolStatus, UnifiedToolResult

        class FakeTool(AbstractTool):
            tool_name = "fake_tool"

            def execute(self, ctx):
                result = UnifiedToolResult(tool_name=self.tool_name, target=ctx.target)
                result.findings = [
                    {
                        "type": "XSS",
                        "severity": "HIGH",
                        "endpoint": ctx.target,
                        "evidence": {"payload": "<script>"},
                        "confidence": 0.8,
                        "source_tool": self.tool_name,
                    }
                ]
                result.findings_count = 1
                result.status = ToolStatus.SUCCESS
                result.mark_finished()
                return result

        monkeypatch.setattr(
            "tools.run_agent_tool.resolve_tool_class", lambda _name: FakeTool
        )
        monkeypatch.setattr(
            "sys.argv",
            [
                "run_agent_tool.py",
                "fake_tool",
                "--target",
                "https://t.example.com",
                "--goal-node-id",
                "goal-1",
                "--intent-node-id",
                "intent-1",
            ],
        )

        with pytest.raises(SystemExit) as exit_info:
            main()

        assert exit_info.value.code == 0
        payload = json.loads(capsys.readouterr().out)
        finding = payload["findings"][0]
        assert finding["goal_node_id"] == "goal-1"
        assert finding["intent_node_id"] == "intent-1"
        assert finding["evidence"]["goal_node_id"] == "goal-1"
        assert payload["goal_node_id"] == "goal-1"

    def test_attribution_can_arrive_in_extra(self, monkeypatch, capsys):
        """Callers that cannot add flags still attribute through --extra."""
        import json

        from tool_core.base import AbstractTool
        from tool_core.result import ToolStatus, UnifiedToolResult

        class FakeTool(AbstractTool):
            tool_name = "fake_tool"

            def execute(self, ctx):
                result = UnifiedToolResult(tool_name=self.tool_name, target=ctx.target)
                result.findings = [
                    {"type": "XSS", "severity": "LOW", "endpoint": ctx.target}
                ]
                result.findings_count = 1
                result.status = ToolStatus.SUCCESS
                result.mark_finished()
                return result

        monkeypatch.setattr(
            "tools.run_agent_tool.resolve_tool_class", lambda _name: FakeTool
        )
        monkeypatch.setattr(
            "sys.argv",
            [
                "run_agent_tool.py",
                "fake_tool",
                "--target",
                "https://t.example.com",
                "--extra",
                json.dumps({"goal_node_id": "goal-2"}),
            ],
        )

        with pytest.raises(SystemExit):
            main()

        payload = json.loads(capsys.readouterr().out)
        assert payload["findings"][0]["goal_node_id"] == "goal-2"
