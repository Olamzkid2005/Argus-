"""Tests for agent.react_agent — Category: class"""

import pytest

from agent.agent_action import AgentAction
from agent.react_agent import ReActAgent
from agent.tool_registry import ToolRegistry


class TestReActAgent:
    """Tests for the ReActAgent class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            ReActAgent()

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            ReActAgent()


# ── Phase 1.2: plan_next_phase / _deterministic_next_phase ────────────


class TestDeterministicNextPhase:
    """Tests for ReActAgent._deterministic_next_phase()."""

    def make_agent(self):
        return ReActAgent(ToolRegistry())

    def test_recon_phase(self):
        """recon phase should return VULN_SCAN and AUTH_TEST."""
        agent = self.make_agent()
        result = agent._deterministic_next_phase([], "recon")
        assert "VULN_SCAN" in result["next_capabilities"]
        assert "AUTH_TEST" in result["next_capabilities"]
        assert result["stop"] is False
        assert "Deterministic phase progression" in result["reasoning"]

    def test_scan_phase(self):
        """scan phase should return DEEP_SCAN, XSS_DETECTION, SQLI_DETECTION."""
        agent = self.make_agent()
        result = agent._deterministic_next_phase([], "scan")
        caps = result["next_capabilities"]
        assert "DEEP_SCAN" in caps
        assert "XSS_DETECTION" in caps
        assert "SQLI_DETECTION" in caps
        assert result["stop"] is False

    def test_deep_scan_phase(self):
        """deep_scan phase should return POST_EXPLOIT and EXPLOIT_CHAIN."""
        agent = self.make_agent()
        result = agent._deterministic_next_phase([], "deep_scan")
        caps = result["next_capabilities"]
        assert "POST_EXPLOIT" in caps
        assert "EXPLOIT_CHAIN" in caps
        assert result["stop"] is False

    def test_repo_scan_phase(self):
        """repo_scan phase should return VULN_SCAN."""
        agent = self.make_agent()
        result = agent._deterministic_next_phase([], "repo_scan")
        assert "VULN_SCAN" in result["next_capabilities"]
        assert result["stop"] is False

    def test_analyze_phase(self):
        """analyze phase should return REPORT."""
        agent = self.make_agent()
        result = agent._deterministic_next_phase([], "analyze")
        assert "REPORT" in result["next_capabilities"]
        assert result["stop"] is False

    def test_report_phase_stops(self):
        """report phase should return empty capabilities and stop."""
        agent = self.make_agent()
        result = agent._deterministic_next_phase([], "report")
        assert result["next_capabilities"] == []
        assert result["stop"] is True

    def test_unknown_phase_falls_back_to_vuln_scan(self):
        """Unknown/empty phase should return VULN_SCAN."""
        agent = self.make_agent()
        result = agent._deterministic_next_phase([], "")
        assert "VULN_SCAN" in result["next_capabilities"]
        assert result["stop"] is False

    def test_critical_findings_in_recon_adds_exploit_capabilities(self):
        """HIGH/CRITICAL findings during recon should add exploit capabilities."""
        agent = self.make_agent()
        findings = [
            {"type": "SQL_INJECTION", "severity": "CRITICAL", "endpoint": "/api"},
            {"type": "XSS", "severity": "HIGH", "endpoint": "/search"},
        ]
        result = agent._deterministic_next_phase(findings, "recon")
        caps = result["next_capabilities"]
        assert "VULN_SCAN" in caps
        assert "AUTH_TEST" in caps
        assert "EXPLOIT_CHAIN" in caps
        assert "POST_EXPLOIT" in caps

    def test_critical_findings_in_scan_adds_exploit_capabilities(self):
        """HIGH/CRITICAL findings during scan should add exploit capabilities."""
        agent = self.make_agent()
        findings = [
            {"type": "RCE", "severity": "CRITICAL", "endpoint": "/exec"},
        ]
        result = agent._deterministic_next_phase(findings, "scan")
        caps = result["next_capabilities"]
        assert "DEEP_SCAN" in caps
        assert "EXPLOIT_CHAIN" in caps
        assert "POST_EXPLOIT" in caps

    def test_no_critical_findings_does_not_add_exploit(self):
        """LOW findings should NOT add exploit capabilities."""
        agent = self.make_agent()
        findings = [
            {"type": "INFO", "severity": "LOW", "endpoint": "/robots.txt"},
        ]
        result = agent._deterministic_next_phase(findings, "recon")
        caps = result["next_capabilities"]
        assert "VULN_SCAN" in caps
        assert "EXPLOIT_CHAIN" not in caps
        assert "POST_EXPLOIT" not in caps

    def test_case_insensitive_phase(self):
        """Phase should be matched case-insensitively."""
        agent = self.make_agent()
        result = agent._deterministic_next_phase([], "RECON")
        assert "VULN_SCAN" in result["next_capabilities"]
        assert result["stop"] is False

    def test_whitespace_stripped_phase(self):
        """Leading/trailing whitespace in phase should be stripped."""
        agent = self.make_agent()
        result = agent._deterministic_next_phase([], "  scan  ")
        assert "DEEP_SCAN" in result["next_capabilities"]

    def test_stop_when_no_next_capabilities(self):
        """stop should be True when no next capabilities exist."""
        agent = self.make_agent()
        result = agent._deterministic_next_phase([], "report")
        assert result["stop"] is True
        assert result["next_capabilities"] == []


class TestPlanNextPhase:
    """Tests for ReActAgent.plan_next_phase().

    These tests verify the fallback-to-deterministic behavior when LLM is
    unavailable — the core error-handling path. LLM integration tests
    would require a live API key.
    """

    def make_agent(self, llm_client=None):
        return ReActAgent(ToolRegistry(), llm_client=llm_client)

    def test_no_llm_client_falls_back_to_deterministic(self):
        """Without llm_client, should fall back to deterministic progression."""
        agent = self.make_agent()
        result = agent.plan_next_phase([], phase="scan", target="http://test.com")
        assert "DEEP_SCAN" in result["next_capabilities"]
        assert "reasoning" in result
        assert "Deterministic" in result["reasoning"]

    def test_unavailable_llm_falls_back(self):
        """When llm_client.is_available() returns False, fall back."""
        mock = _MockLLMClient(available=False)
        agent = self.make_agent(llm_client=mock)
        result = agent.plan_next_phase([], phase="deep_scan")
        assert "POST_EXPLOIT" in result["next_capabilities"]
        assert "Deterministic" in result["reasoning"]

    def test_empty_phase_defaults_to_vuln_scan(self):
        """Empty/unknown phase should fall back to VULN_SCAN."""
        agent = self.make_agent()
        result = agent.plan_next_phase([], phase="")
        assert "VULN_SCAN" in result["next_capabilities"]

    def test_findings_passed_to_deterministic_fallback(self):
        """Findings should be passed to deterministic fallback for severity analysis."""
        agent = self.make_agent()
        findings = [{"type": "RCE", "severity": "CRITICAL"}]
        result = agent.plan_next_phase(findings, phase="recon")
        assert "EXPLOIT_CHAIN" in result["next_capabilities"]
        assert "POST_EXPLOIT" in result["next_capabilities"]


# ── LLM client test doubles ──


class _MockLLMClient:
    """Test double for LLMClient that controls is_available()."""

    def __init__(self, available: bool = False):
        self._available = available

    def is_available(self) -> bool:
        return self._available


class _BrokenLLMClient:
    """Test double for LLMClient that raises on is_available()."""

    def is_available(self):
        raise RuntimeError("Connection failed")


class _SelectingLLMClient:
    """Test double that returns a fixed JSON tool selection."""

    def __init__(self, payload: str, input_tokens: int = 321, output_tokens: int = 45):
        self.model = "test-model"
        self._payload = payload
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens

    def is_available(self) -> bool:
        return True

    def chat_sync(self, messages, **kwargs):
        from llm_client import LLMResponse

        return LLMResponse(
            text=self._payload,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            cost_usd=0.000123,
        )


class _CountingLLMClient(_SelectingLLMClient):
    """A selecting client that also records whether it was consulted."""

    def __init__(self, payload: str):
        super().__init__(payload)
        self.calls = 0

    def chat_sync(self, messages, **kwargs):
        self.calls += 1
        return super().chat_sync(messages, **kwargs)


class _ExplodingLLMClient:
    """Test double whose calls fail, as a 503 from the provider would."""

    model = "test-model"

    def is_available(self) -> bool:
        return True

    def chat_sync(self, messages, **kwargs):
        raise RuntimeError("503 Service Unavailable")


class TestActionProvenance:
    """`was_fallback` must record who chose the tool, not whether an LLM was reachable.

    Both audit records — the `agent_decisions` row and the SSE decision event —
    answer "did the engine choose this tool?". The earlier rule keyed off
    `llm_client.is_available()`, so an LLM client that was configured but
    failing (the agent then uses deterministic ordering) was still recorded as
    `was_fallback=False`.
    """

    @staticmethod
    def _noop_tool():
        return {}

    def _agent_with_tool(self, llm_client):
        registry = ToolRegistry()
        registry.register(
            "httpx",
            self._noop_tool,
            {"name": "httpx", "description": "HTTP probe", "parameters": []},
        )
        return ReActAgent(registry, llm_client=llm_client)

    def _recon(self):
        from models.recon_context import ReconContext

        return ReconContext(
            target_url="http://127.0.0.1:55693",
            live_endpoints=["http://127.0.0.1:55693/health"],
        )

    def test_llm_choice_is_sourced_as_llm_and_carries_tokens(self):
        agent = self._agent_with_tool(
            _SelectingLLMClient('{"tool": "httpx", "reasoning": "probe the health endpoint"}')
        )
        action = agent.plan_next_action(
            "scan: http://127.0.0.1:55693", "no observations yet", recon_context=self._recon()
        )

        assert action is not None
        assert action.tool == "httpx"
        assert action.reasoning == "probe the health endpoint"
        assert action.source == "llm"
        assert ReActAgent._is_fallback_action(action) is False
        # The counts must survive to the audit row, not just to governance.
        assert (action.input_tokens, action.output_tokens) == (321, 45)

    def test_llm_failure_is_marked_a_fallback(self):
        agent = self._agent_with_tool(_ExplodingLLMClient())
        action = agent.plan_next_action(
            "scan: http://127.0.0.1:55693", "no observations yet", recon_context=self._recon()
        )

        assert action is not None
        assert action.source != "llm"
        assert ReActAgent._is_fallback_action(action) is True

    def test_action_without_provenance_counts_as_a_fallback(self):
        action = AgentAction("httpx", {}, "Trying httpx")
        assert ReActAgent._is_fallback_action(action) is True
        assert (action.input_tokens, action.output_tokens) == (0, 0)
        assert action.to_dict()["source"] == ""


class TestTriedToolEnforcement:
    """A tool this run already put behind it must not be chosen again.

    `tried_tools` is rendered into the selection prompt, but a small model
    ignores it: a live scan had the agent propose `nuclei` ten iterations in a
    row, each refused by scope validation, each costing an LLM call while the
    run advanced nothing.
    """

    @staticmethod
    def _noop_tool():
        return {}

    def _agent(self, llm_client, tools=("httpx", "nuclei")):
        registry = ToolRegistry()
        for name in tools:
            registry.register(
                name,
                self._noop_tool,
                {"name": name, "description": f"{name} probe", "parameters": []},
            )
        return ReActAgent(registry, llm_client=llm_client)

    def _recon(self):
        from models.recon_context import ReconContext

        return ReconContext(
            target_url="http://127.0.0.1:55693",
            live_endpoints=["http://127.0.0.1:55693/health"],
        )

    def test_reselecting_a_tried_tool_is_rejected(self):
        agent = self._agent(
            _SelectingLLMClient('{"tool": "nuclei", "reasoning": "nuclei again"}')
        )
        action = agent.plan_next_action(
            "scan: http://127.0.0.1:55693",
            "ctx",
            tried_tools={"nuclei"},
            recon_context=self._recon(),
        )

        assert action is not None
        assert action.tool != "nuclei"
        assert ReActAgent._is_fallback_action(action) is True
        assert agent._llm_failure_count == 1

    def test_a_degraded_run_stops_consulting_the_llm(self):
        """The DEGRADED policy ("switch to deterministic ordering") must bite.

        Nothing consumed that recommendation, so a run whose selections kept
        being refused kept buying LLM calls that could not change the outcome.
        """
        from models.recon_context import ReconContext
        from runtime.degradation_awareness import DegradationAwareness

        degradation = DegradationAwareness("ENG-degraded-test")
        for _ in range(6):
            degradation.record_llm_result(success=False)
        assert degradation.get_status().llm_success_rate < 0.5

        client = _CountingLLMClient('{"tool": "nuclei", "reasoning": "from llm"}')
        agent = self._agent(client)
        agent._degradation_awareness = degradation

        action = agent.plan_next_action(
            "scan: http://127.0.0.1:55693",
            "ctx",
            recon_context=ReconContext(target_url="http://127.0.0.1:55693"),
        )

        assert client.calls == 0
        assert action is not None
        assert ReActAgent._is_fallback_action(action) is True
        assert agent._llm_failure_count == 0

    def test_an_untried_selection_is_still_accepted(self):
        agent = self._agent(
            _SelectingLLMClient('{"tool": "nuclei", "reasoning": "fresh choice"}')
        )
        action = agent.plan_next_action(
            "scan: http://127.0.0.1:55693",
            "ctx",
            tried_tools={"httpx"},
            recon_context=self._recon(),
        )

        assert action is not None
        assert action.tool == "nuclei"
        assert action.source == "llm"
        assert agent._llm_failure_count == 0
