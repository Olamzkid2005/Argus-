"""Tests for the multi-agent swarm system."""

from agent.swarm import APIAgent, AuthAgent, IDORAgent, SwarmOrchestrator
from models.recon_context import ReconContext


class TestSpecialistAgentActivation:
    def test_idor_agent_activates_when_api_present(self):
        rc = ReconContext(
            has_api=True,
            api_endpoints=["/api/v1/users", "/api/v1/orders"],
            parameter_bearing_urls=["/search?q="],
        )
        agent = IDORAgent(None, None, rc, "test-id")
        assert agent.should_activate() is True

    def test_idor_agent_skips_when_no_signals(self):
        rc = ReconContext(has_api=False, api_endpoints=[])
        agent = IDORAgent(None, None, rc, "test-id")
        assert agent.should_activate() is False

    def test_auth_agent_activates_when_login_page_exists(self):
        rc = ReconContext(
            has_login_page=True, auth_endpoints=["/login"]
        )
        agent = AuthAgent(None, None, rc, "test-id")
        assert agent.should_activate() is True

    def test_auth_agent_skips_when_no_auth_signals(self):
        rc = ReconContext(
            has_login_page=False, auth_endpoints=[], has_api=False
        )
        agent = AuthAgent(None, None, rc, "test-id")
        assert agent.should_activate() is False

    def test_api_agent_activates_when_many_endpoints(self):
        rc = ReconContext(
            has_api=True,
            api_endpoints=[f"/api/v{x}" for x in range(10)],
        )
        agent = APIAgent(None, None, rc, "test-id")
        assert agent.should_activate() is True

    def test_api_agent_skips_when_few_endpoints(self):
        rc = ReconContext(
            has_api=True, api_endpoints=["/api/v1/health"]
        )
        agent = APIAgent(None, None, rc, "test-id")
        assert agent.should_activate() is False


class TestSwarmDedup:
    def test_deduplicates_by_type_and_endpoint(self):
        findings = [
            {
                "type": "XSS",
                "endpoint": "http://ex.com/search",
                "confidence": 0.8,
                "evidence": {"payload": "<script>alert(1)</script>"},
            },
            {
                "type": "XSS",
                "endpoint": "http://ex.com/search",
                "confidence": 0.9,
                "evidence": {"payload": "<script>alert(1)</script>"},
            },
        ]
        result = SwarmOrchestrator._deduplicate(findings)
        assert len(result) == 1
        assert result[0]["confidence"] == 0.9

    def test_different_types_kept_separate(self):
        findings = [
            {
                "type": "XSS",
                "endpoint": "http://ex.com/search",
                "confidence": 0.8,
            },
            {
                "type": "SQLI",
                "endpoint": "http://ex.com/search",
                "confidence": 0.9,
            },
        ]
        result = SwarmOrchestrator._deduplicate(findings)
        assert len(result) == 2

    def test_same_confidence_richer_evidence_wins(self):
        findings = [
            {
                "type": "XSS",
                "endpoint": "http://ex.com/search",
                "confidence": 0.8,
                "evidence": {"payload": "x"},
            },
            {
                "type": "XSS",
                "endpoint": "http://ex.com/search",
                "confidence": 0.8,
                "evidence": {
                    "request": "GET ...",
                    "response": "200 ... <script>...</script>",
                    "payload": "<script>alert(document.cookie)</script>",
                },
            },
        ]
        result = SwarmOrchestrator._deduplicate(findings)
        assert len(result) == 1
        assert len(str(result[0]["evidence"])) > 50


class TestDeepCopy:
    def test_agents_get_independent_contexts(self):
        """Verify deep copy prevents shared state mutation."""
        rc = ReconContext(
            has_api=True, api_endpoints=["/api/v1/users"]
        )
        agent1 = IDORAgent(None, None, rc, "test-id")
        agent2 = AuthAgent(None, None, rc, "test-id")

        # Mutate agent1's context
        if agent1.recon_context:
            agent1.recon_context.has_api = False

        # Agent2 should have the original value
        assert agent2.recon_context.has_api is True
