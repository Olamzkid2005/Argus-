"""Tests for agent.react_agent — Category: class"""

import pytest

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
