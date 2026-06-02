"""
Full integration test suite for the LLM ReAct agent pipeline.

Tests the complete flow with mocked LLM responses and mocked tool execution.
Verifies the agent correctly selects tools, handles edge cases, and falls back.
"""
import os
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent import (
    AgentResult,
    ReActAgent,
    ToolRegistry,
)
from models.recon_context import ReconContext

MOCK_SCAN_DECISIONS = [
    '{"tool": "arjun", "arguments": {"target": "http://test.local"}, "reasoning": "API found, discovering params first"}',
    '{"tool": "nuclei", "arguments": {"target": "http://test.local"}, "reasoning": "Scan endpoints for vulns"}',
    '{"tool": "__done__", "arguments": {}, "reasoning": "Sufficient coverage achieved"}',
]


@pytest.fixture
def recon_context():
    return ReconContext(
        target_url="http://test.local",
        live_endpoints=["http://test.local/api", "http://test.local/login"],
        tech_stack=["nginx", "Python"],
        has_api=True,
        has_login_page=True,
        findings_count=50,
    )


@pytest.fixture
def tool_registry():
    registry = ToolRegistry()
    registry.register("nuclei", lambda _target="", **_kw: AgentResult(tool="nuclei", success=True, output="[vuln] XSS found", findings=[{"type": "XSS"}]),
                      {"name": "nuclei", "description": "Vuln scanner", "parameters": [{"name": "target", "required": True}]})
    registry.register("arjun", lambda _target="", **_kw: AgentResult(tool="arjun", success=True, output="[param] id found", findings=[{"type": "PARAM"}]),
                      {"name": "arjun", "description": "Param discovery", "parameters": [{"name": "target", "required": True}]})
    registry.register("dalfox", lambda _target="", **_kw: AgentResult(tool="dalfox", success=True, output="[xss] reflected", findings=[{"type": "XSS"}]),
                      {"name": "dalfox", "description": "XSS scanner", "parameters": [{"name": "target", "required": True}]})
    registry.register("sqlmap", lambda _target="", **_kw: AgentResult(tool="sqlmap", success=True, output="[sqli] time-based", findings=[{"type": "SQLI"}]),
                      {"name": "sqlmap", "description": "SQLi scanner", "parameters": [{"name": "target", "required": True}]})
    return registry


class TestFullAgentScan:
    """Integration tests for full agent-driven scan pipeline."""

    def test_full_agent_scan_calls_llm_selected_tools(self, tool_registry, recon_context):
        """Agent should call ONLY tools the LLM selects (not all deterministic tools)."""
        mock_llm = Mock()
        mock_llm.is_available.return_value = True
        decision_iter = iter(MOCK_SCAN_DECISIONS)
        mock_llm.chat_sync.side_effect = lambda *_a, **_kw: next(decision_iter)

        agent = ReActAgent(tool_registry, llm_client=mock_llm, engagement_id="test-123", phase="scan")
        results = agent.run(task="scan: http://test.local", recon_context=recon_context)

        called_tools = [r.tool for r in results]
        assert "arjun" in called_tools, "LLM selected arjun first"
        assert "nuclei" in called_tools, "LLM selected nuclei second"
        assert "sqlmap" not in called_tools, "LLM said done before sqlmap"
        assert len(called_tools) == 2, f"Expected 2 tools, got {len(called_tools)}: {called_tools}"

    def test_full_agent_scan_fallback_on_llm_error(self, tool_registry, recon_context):
        """When LLM errors, all deterministic phase tools (that are registered) should be called."""
        mock_llm = Mock()
        mock_llm.is_available.return_value = True
        mock_llm.chat_sync.side_effect = Exception("API unavailable")

        agent = ReActAgent(tool_registry, llm_client=mock_llm, engagement_id="test-123", phase="scan")
        results = agent.run(task="scan: http://test.local", recon_context=recon_context)

        called_tools = [r.tool for r in results]
        # Only tools that are registered should be called
        assert len(called_tools) == 4, f"Expected 4 registered tools in fallback, got {called_tools}"

    def test_agent_respects_max_iterations(self):
        """Agent should stop after max_iterations even if more tools available."""
        registry = ToolRegistry()
        for i in range(10):
            registry.register(f"tool_{i}", lambda _target="", **_kw: AgentResult(tool="", success=True, output="ok"),
                              {"name": f"tool_{i}", "description": "", "parameters": []})

        agent = ReActAgent(registry, max_iterations=3)
        results = agent.run(task="scan: test")
        assert len(results) <= 3

    def test_scope_violation_skips_tool(self, tool_registry, recon_context):
        """Out-of-scope target should be blocked by scope validator."""
        from tools.scope_validator import ScopeValidator

        scope_validator = ScopeValidator("test-123", {"domains": ["*.allowed.com"]})
        original_call = tool_registry.call

        def scoped_call(name, **kwargs):
            target = kwargs.get("target", "")
            if target and not scope_validator._matches_domain(target.replace("http://", "").split("/")[0]):
                return AgentResult(tool=name, success=False, error="Scope violation")
            return original_call(name, **kwargs)

        tool_registry.call = scoped_call

        mock_llm = Mock()
        mock_llm.is_available.return_value = True
        mock_llm.chat_sync.return_value = '{"tool": "nuclei", "arguments": {"target": "http://evil.com"}, "reasoning": "test"}'

        agent = ReActAgent(tool_registry, llm_client=mock_llm, engagement_id="test-123", phase="scan")
        results = agent.run(task="scan: http://test.local", recon_context=recon_context)

        # First result should be scope violation
        if results:
            assert not results[0].success

    def test_missing_recon_context_uses_deterministic(self):
        """When recon_context is None, agent should use deterministic fallback."""
        registry = ToolRegistry()
        registry.register("nuclei", lambda _target="", **_kw: AgentResult(tool="nuclei", success=True, output="ok"),
                          {"name": "nuclei", "description": "Vuln scanner", "parameters": []})

        agent = ReActAgent(registry, phase="scan")
        results = agent.run(task="scan: test", recon_context=None)
        assert len(results) > 0

    def test_llm_returns_done_early(self, tool_registry, recon_context):
        """LLM returning __done__ should stop the loop immediately."""
        mock_llm = Mock()
        mock_llm.is_available.return_value = True
        mock_llm.chat_sync.return_value = '{"tool": "__done__", "arguments": {}, "reasoning": "All done"}'

        agent = ReActAgent(tool_registry, llm_client=mock_llm, engagement_id="test-123", phase="scan")
        results = agent.run(task="scan: http://test.local", recon_context=recon_context)
        assert len(results) == 0, "Should have no results when LLM says done immediately"


class TestAgentFallbackRegression:
    """Regression tests: system behaves identically when agent mode is off."""

    def test_no_llm_client_uses_deterministic(self, tool_registry):
        """With no LLM client, deterministic path should run all registered phase tools."""
        agent = ReActAgent(tool_registry, llm_client=None, phase="scan")
        results = agent.run(task="scan: test")
        registered = len(tool_registry.list_tools())
        assert len(results) == registered, f"Expected {registered} registered tools, got {len(results)}"

    def test_agent_mode_false_bypasses_llm(self, tool_registry, recon_context):
        """When agent_mode is conceptually False (no llm_client), skip LLM."""
        agent = ReActAgent(tool_registry, llm_client=None, phase="scan")
        results = agent.run(task="scan: test", recon_context=recon_context)
        registered = len(tool_registry.list_tools())
        assert len(results) == registered

    def test_deterministic_order_preserved(self):
        """Deterministic tools should be tried in PHASE_TOOLS order."""
        registry = ToolRegistry()
        called = []

        for name in ["z_tool", "a_tool", "m_tool"]:
            def make_fn(tn):
                def fn(target="", **kw):
                    called.append(tn)
                    return AgentResult(tool=tn, success=True, output="ok", findings=[{"id": tn}])
                return fn
            registry.register(name, make_fn(name),
                              {"name": name, "description": "", "parameters": []})

        agent = ReActAgent(registry, max_iterations=10)
        original = ReActAgent.PHASE_TOOLS
        ReActAgent.PHASE_TOOLS = {"scan": ["z_tool", "a_tool", "m_tool"]}
        agent._phase = "scan"
        try:
            agent.run(task="scan: test")
            assert called == ["z_tool", "a_tool", "m_tool"], f"Expected order z, a, m but got {called}"
        finally:
            ReActAgent.PHASE_TOOLS = original

    def test_deterministic_empty_phase(self):
        """Phase with no tools should return empty results."""
        registry = ToolRegistry()
        agent = ReActAgent(registry, max_iterations=5)
        agent._phase = "nonexistent"
        results = agent.run(task="nonexistent: test")
        assert results == []
