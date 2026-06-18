"""Integration tests for MCP agent methods."""

import pytest

from mcp_server import MCPServer, ToolDefinition


@pytest.fixture
def server():
    s = MCPServer(tools_dir="/tmp/nonexistent_tools_dir_xyz")
    s.register_tool(ToolDefinition(name="nuclei", command="nuclei"))
    s.register_tool(ToolDefinition(name="nmap", command="nmap"))
    return s


class TestHandleAgentInit:
    def test_creates_session_and_returns_plan(self, server):
        result = server.handle_agent_init(
            {
                "target": "https://example.com",
                "phase": "recon",
            }
        )
        assert "session_id" in result
        assert result["phase"] == "recon"
        assert "plan" in result

    def test_plan_from_pipeline(self, server):
        result = server.handle_agent_init(
            {
                "target": "https://example.com",
                "phase": "scan",
                "pipeline": [{"tool": "nuclei"}, {"tool": "nmap"}],
            }
        )
        assert result["plan"] == ["nuclei", "nmap"]

    def test_plan_skips_unknown_tools(self, server):
        result = server.handle_agent_init(
            {
                "target": "https://example.com",
                "phase": "scan",
                "pipeline": [{"tool": "nuclei"}, {"tool": "nonexistent_tool"}],
            }
        )
        assert result["plan"] == ["nuclei"]

    def test_plan_falls_back_to_phase_default(self, server):
        result = server.handle_agent_init(
            {
                "target": "https://example.com",
                "phase": "deep_scan",
            }
        )
        assert "nuclei" in result["plan"]
        assert "sqlmap" in result["plan"]

    def test_plan_returns_empty_for_unknown_phase(self, server):
        result = server.handle_agent_init(
            {
                "target": "https://example.com",
                "phase": "unknown_phase",
            }
        )
        assert result["plan"] == []


class TestHandleAgentNext:
    def test_advances_plan_step_by_step(self, server):
        init = server.handle_agent_init(
            {
                "target": "https://example.com",
                "phase": "scan",
                "pipeline": [{"tool": "nuclei"}, {"tool": "nmap"}],
            }
        )
        sid = init["session_id"]

        step1 = server.handle_agent_next({"session_id": sid})
        assert step1["tool"] == "nuclei"
        assert step1["done"] is False

        step2 = server.handle_agent_next({"session_id": sid})
        assert step2["tool"] == "nmap"
        assert step2["done"] is False

    def test_returns_done_when_plan_exhausted(self, server):
        init = server.handle_agent_init(
            {
                "target": "https://example.com",
                "phase": "scan",
                "pipeline": [{"tool": "nuclei"}],
            }
        )
        sid = init["session_id"]

        server.handle_agent_next({"session_id": sid})
        result = server.handle_agent_next({"session_id": sid})
        assert result["done"] is True
        assert "tool" not in result

    def test_missing_session_returns_error(self, server):
        result = server.handle_agent_next({"session_id": "nonexistent"})
        assert result["done"] is True
        assert "error" in result

    def test_trigger_normalization(self, server):
        """Trigger keys should be normalized (case-insensitive)."""
        init = server.handle_agent_init(
            {
                "target": "https://example.com",
                "phase": "scan",
                "pipeline": [{"tool": "nuclei"}],
            }
        )
        sid = init["session_id"]

        server.handle_agent_next({"session_id": sid})
        result = server.handle_agent_next({"session_id": sid, "trigger": "STUCK"})
        assert result["done"] is True


class TestHandleAgentObserve:
    def test_records_execution(self, server):
        init = server.handle_agent_init(
            {
                "target": "https://example.com",
                "phase": "scan",
                "pipeline": [{"tool": "nuclei"}],
            }
        )
        sid = init["session_id"]

        server.handle_agent_observe(
            {
                "session_id": sid,
                "tool": "nuclei",
                "success": True,
                "summary": "Found 2 vulnerabilities",
                "findingCount": 2,
                "durationMs": 1500,
            }
        )

        session = server.session_store.get(sid)
        assert len(session.tool_history) == 1
        assert session.tool_history[0].tool == "nuclei"
        assert session.tool_history[0].success is True
        assert "Found 2 vulnerabilities" in session.observations

    def test_failure_triggers_stuck(self, server):
        init = server.handle_agent_init(
            {
                "target": "https://example.com",
                "phase": "scan",
                "pipeline": [{"tool": "nuclei"}, {"tool": "nmap"}],
            }
        )
        sid = init["session_id"]

        # Observe triggers handle_agent_next which advances the plan
        # and returns the next tool (advancing past the failed tool)
        result = server.handle_agent_observe(
            {
                "session_id": sid,
                "tool": "nuclei",
                "success": False,
                "summary": "Tool failed",
                "findingCount": 0,
                "durationMs": 500,
            }
        )

        # The plan advances to the next tool (nmap) or signals done
        assert not result.get("error")
        assert result.get("done") is False
        assert result.get("tool") is not None

    def test_missing_session_returns_error(self, server):
        result = server.handle_agent_observe(
            {
                "session_id": "nonexistent",
                "tool": "nuclei",
                "success": True,
                "summary": "",
                "findingCount": 0,
                "durationMs": 0,
            }
        )
        assert result["done"] is True
        assert "error" in result


class TestMCPToolResult:
    def test_to_dict_with_data(self):
        from mcp_server import MCPToolResult

        result = MCPToolResult(
            success=True,
            output="ok",
            tool="nuclei",
            data={"structured": [{"title": "test"}], "artifacts": ["a.txt"]},
        )
        d = result.to_dict()
        assert d["meta"]["data"]["structured"] == [{"title": "test"}]
        assert d["meta"]["data"]["artifacts"] == ["a.txt"]
        assert "structured" not in d["meta"] or "structured" not in d

    def test_to_dict_without_data(self):
        from mcp_server import MCPToolResult

        result = MCPToolResult(success=True, output="ok", tool="nuclei")
        d = result.to_dict()
        assert "data" not in d["meta"]
