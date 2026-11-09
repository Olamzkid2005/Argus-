"""Integration tests for MCP agent methods."""

from unittest.mock import patch

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

    @patch("mcp_server.LLMClient")
    def test_plan_from_pipeline(self, mock_llm, server):
        mock_llm.return_value.is_available.return_value = False
        result = server.handle_agent_init(
            {
                "target": "https://example.com",
                "phase": "scan",
                "pipeline": [{"tool": "nuclei"}, {"tool": "nmap"}],
            }
        )
        assert result["plan"] == ["nuclei", "nmap"]

    @patch("mcp_server.LLMClient")
    def test_plan_skips_unknown_tools(self, mock_llm, server):
        mock_llm.return_value.is_available.return_value = False
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
    @patch("mcp_server.LLMClient")
    def test_advances_plan_step_by_step(self, mock_llm, server):
        mock_llm.return_value.is_available.return_value = False
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

    @patch("mcp_server.LLMClient")
    def test_returns_done_when_plan_exhausted(self, mock_llm, server):
        mock_llm.return_value.is_available.return_value = False
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

    @patch("mcp_server.LLMClient")
    def test_trigger_normalization(self, mock_llm, server):
        """Trigger keys should be normalized (case-insensitive)."""
        mock_llm.return_value.is_available.return_value = False
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
    @patch("mcp_server.LLMClient")
    def test_records_execution(self, mock_llm, server):
        mock_llm.return_value.is_available.return_value = False
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

    @patch("mcp_server.LLMClient")
    def test_observe_acknowledges_without_advancing(self, mock_llm, server):
        """2.2: `agent_observe` records the result and acknowledges it — it
        must not consume the next plan step. Only `agent_next` advances."""
        mock_llm.return_value.is_available.return_value = False
        init = server.handle_agent_init(
            {
                "target": "https://example.com",
                "phase": "scan",
                "pipeline": [{"tool": "nuclei"}, {"tool": "nmap"}],
            }
        )
        sid = init["session_id"]

        first = server.handle_agent_next({"session_id": sid})
        assert first["tool"] == "nuclei"

        # A failed observation is acknowledged, not advanced past.
        result = server.handle_agent_observe(
            {
                "session_id": sid,
                "action_id": first["action_id"],
                "tool": "nuclei",
                "success": False,
                "summary": "Tool failed",
                "findingCount": 0,
                "durationMs": 500,
            }
        )
        assert result.get("recorded") is True
        assert result.get("error") is None
        assert "tool" not in result

        # The middle action was not skipped: the next step is nmap.
        second = server.handle_agent_next({"session_id": sid})
        assert second["tool"] == "nmap"
        assert second["action_id"] != first["action_id"]

    @patch("mcp_server.LLMClient")
    def test_three_actions_execute_exactly_once_in_order(self, mock_llm, server):
        """2.2 verification: next/observe/next/observe/next runs three
        planned actions exactly once each, in plan order."""
        mock_llm.return_value.is_available.return_value = False
        server.register_tool(ToolDefinition(name="httpx", command="httpx"))
        init = server.handle_agent_init(
            {
                "target": "https://example.com",
                "phase": "scan",
                "pipeline": [{"tool": "nuclei"}, {"tool": "nmap"}, {"tool": "httpx"}],
            }
        )
        sid = init["session_id"]

        seen = []
        for _ in range(3):
            nxt = server.handle_agent_next({"session_id": sid})
            assert nxt["done"] is False
            seen.append(nxt["tool"])
            ack = server.handle_agent_observe(
                {
                    "session_id": sid,
                    "action_id": nxt["action_id"],
                    "tool": nxt["tool"],
                    "arguments": nxt["arguments"],
                    "success": True,
                    "summary": f"{nxt['tool']} ok",
                    "findingCount": 0,
                    "durationMs": 100,
                }
            )
            assert ack.get("recorded") is True

        assert seen == ["nuclei", "nmap", "httpx"]
        assert server.handle_agent_next({"session_id": sid})["done"] is True
        session = server.session_store.get(sid)
        assert [ex.tool for ex in session.tool_history] == seen

    @patch("mcp_server.LLMClient")
    def test_next_carries_action_id_arguments_and_provenance(self, mock_llm, server):
        """2.2: the issued action carries its id, validated arguments,
        reasoning, chooser provenance, and engagement identity."""
        mock_llm.return_value.is_available.return_value = False
        init = server.handle_agent_init(
            {
                "target": "https://example.com",
                "phase": "scan",
                "engagementId": "ENG-123",
                "pipeline": [{"tool": "nuclei"}],
            }
        )
        sid = init["session_id"]
        nxt = server.handle_agent_next({"session_id": sid})
        assert nxt["action_id"]
        # Arguments reach the runner from the authorized session target —
        # never from model free-text.
        assert nxt["arguments"] == {"target": "https://example.com"}
        assert nxt["provenance"] in ("llm", "deterministic")
        assert nxt["reasoning"]
        assert nxt["engagement_id"] == "ENG-123"

    @patch("mcp_server.LLMClient")
    def test_unknown_action_is_rejected(self, mock_llm, server):
        """2.2: an observation for an unknown action_id is rejected and not
        recorded."""
        mock_llm.return_value.is_available.return_value = False
        init = server.handle_agent_init(
            {
                "target": "https://example.com",
                "phase": "scan",
                "pipeline": [{"tool": "nuclei"}],
            }
        )
        sid = init["session_id"]
        server.handle_agent_next({"session_id": sid})

        result = server.handle_agent_observe(
            {
                "session_id": sid,
                "action_id": "deadbeef-9999",
                "tool": "nuclei",
                "success": True,
                "summary": "spoofed",
                "findingCount": 0,
                "durationMs": 10,
            }
        )
        assert result.get("recorded") is False
        assert "Unknown action" in (result.get("error") or "")
        session = server.session_store.get(sid)
        assert len(session.tool_history) == 0

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


class TestHandleAgentInitLlmHandoff:
    """`agent_init.llm` decides which model the worker uses for this run.

    The planner resolves the model (it can see OpenCode's provider registry) and
    the worker adopts it, so one run cannot be planned by one model and executed
    by another.
    """

    HANDOFF = {
        "provider": "openai-compatible",
        "providerID": "opencode-go",
        "model": "kimi-k2.7-code",
        "apiKey": "sk-driver-key-1234567890",
        "baseUrl": "https://opencode.ai/zen/go/v1",
    }

    def teardown_method(self):
        from config.llm_env import set_worker_llm_config

        set_worker_llm_config(None)

    def test_adopts_the_driver_model(self, server):
        from config.llm_env import worker_llm_config

        server.handle_agent_init(
            {"target": "https://example.com", "phase": "recon", "llm": self.HANDOFF}
        )

        config = worker_llm_config()
        assert config is not None
        assert config.model == "kimi-k2.7-code"
        assert config.api_url == "https://opencode.ai/zen/go/v1/chat/completions"

    def test_no_llm_block_leaves_the_worker_config_alone(self, server):
        from config.llm_env import set_worker_llm_config, worker_llm_config

        set_worker_llm_config(self.HANDOFF)
        server.handle_agent_init({"target": "https://example.com", "phase": "recon"})

        assert worker_llm_config() is not None

    def test_invalid_llm_block_is_ignored_not_fatal(self, server):
        from config.llm_env import worker_llm_config

        result = server.handle_agent_init(
            {
                "target": "https://example.com",
                "phase": "recon",
                "llm": {"provider": "anthropic", "model": "claude"},
            }
        )

        assert "session_id" in result  # the phase still starts
        assert worker_llm_config() is None  # but the bad block was not adopted


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
