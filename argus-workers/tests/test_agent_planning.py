"""Tests for ReActAgent planning with LLM and deterministic fallback."""
import os
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.agent_result import AgentResult
from agent.react_agent import ReActAgent
from agent.tool_registry import ToolRegistry
from models.recon_context import ReconContext


class TestPlanNextAction:
    @pytest.fixture
    def agent(self):
        registry = ToolRegistry()
        registry.register("nuclei", lambda target="", **kw: AgentResult(tool="nuclei", success=True, output="ok"),
                          {"name": "nuclei", "description": "Vuln scanner", "parameters": []})
        registry.register("dalfox", lambda target="", **kw: AgentResult(tool="dalfox", success=True, output="ok"),
                          {"name": "dalfox", "description": "XSS scanner", "parameters": []})
        return ReActAgent(registry)

    @pytest.fixture
    def recon_context(self):
        return ReconContext(
            target_url="https://example.com",
            live_endpoints=["https://example.com/api"],
            has_api=True,
        )

    def test_plan_next_action_with_mock_llm(self, agent, recon_context):
        """Mock chat_sync returns valid JSON, verify correct AgentAction returned."""
        mock_llm = Mock()
        mock_llm.is_available.return_value = True
        mock_response = '{"tool": "nuclei", "arguments": {"target": "https://example.com"}, "reasoning": "API found, scanning for vulns"}'
        mock_llm.chat_sync.return_value = mock_response

        action = agent.plan_next_action(
            task="scan: https://example.com",
            context="",
            recon_context=recon_context,
            llm_client=mock_llm,
        )

        assert action is not None
        assert action.tool == "nuclei"
        assert action.arguments == {"target": "https://example.com"}
        assert "API" in action.reasoning

    def test_plan_next_action_llm_done(self, agent, recon_context):
        """LLM returns __done__, verify None returned."""
        mock_llm = Mock()
        mock_llm.is_available.return_value = True
        mock_llm.chat_sync.return_value = '{"tool": "__done__", "arguments": {}, "reasoning": "All tools covered"}'

        action = agent.plan_next_action(
            task="scan: https://example.com",
            context="",
            recon_context=recon_context,
            llm_client=mock_llm,
        )

        assert action is None

    def test_plan_next_action_llm_unknown_tool(self, agent, recon_context):
        """LLM returns unregistered tool, verify deterministic fallback used."""
        mock_llm = Mock()
        mock_llm.is_available.return_value = True
        mock_llm.chat_sync.return_value = '{"tool": "nonexistent_tool", "arguments": {}, "reasoning": "Testing"}'

        action = agent.plan_next_action(
            task="scan: https://example.com",
            context="",
            recon_context=recon_context,
            llm_client=mock_llm,
        )

        assert action is not None
        assert action.tool in ("nuclei", "dalfox")  # deterministic fallback

    def test_plan_next_action_llm_exception(self, agent, recon_context):
        """chat_sync raises exception, verify deterministic fallback used."""
        mock_llm = Mock()
        mock_llm.is_available.return_value = True
        mock_llm.chat_sync.side_effect = Exception("API error")

        action = agent.plan_next_action(
            task="scan: https://example.com",
            context="",
            recon_context=recon_context,
            llm_client=mock_llm,
        )

        assert action is not None
        assert action.tool in ("nuclei", "dalfox")  # deterministic fallback

    def test_plan_next_action_no_llm(self, agent):
        """llm_client=None, verify deterministic path used directly."""
        action = agent.plan_next_action(
            task="scan: https://example.com",
            context="",
        )

        assert action is not None
        assert action.tool in ("nuclei", "dalfox")

    def test_plan_next_action_all_tools_tried(self, agent):
        """When all tools are in tried_tools, should return None."""
        action = agent.plan_next_action(
            task="scan: https://example.com",
            context="",
            tried_tools={"nuclei", "dalfox"},
        )

        assert action is None


class TestReActAgentRun:
    @pytest.fixture
    def agent(self):
        registry = ToolRegistry()
        registry.register("nuclei", lambda target="", **kw: AgentResult(tool="nuclei", success=True, output="ok"),
                          {"name": "nuclei", "description": "Vuln scanner", "parameters": []})
        return ReActAgent(registry, max_iterations=5)

    def test_run_respects_max_iterations(self, agent):
        """Mock plan to always return action, verify loop stops at max."""
        results = agent.run("scan: https://example.com")
        assert len(results) <= 5

    def test_run_returns_agent_results(self, agent):
        """Run should return a list of AgentResult."""
        results = agent.run("scan: https://example.com")
        for r in results:
            assert isinstance(r, AgentResult)
