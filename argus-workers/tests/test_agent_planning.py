"""Tests for ReActAgent planning with LLM and deterministic fallback."""

import os
import sys
from unittest.mock import Mock, patch

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
        registry.register(
            "nuclei",
            lambda _target="", **_kw: AgentResult(
                tool="nuclei", success=True, output="ok"
            ),
            {"name": "nuclei", "description": "Vuln scanner", "parameters": []},
        )
        registry.register(
            "dalfox",
            lambda _target="", **_kw: AgentResult(
                tool="dalfox", success=True, output="ok"
            ),
            {"name": "dalfox", "description": "XSS scanner", "parameters": []},
        )
        return ReActAgent(registry)

    @pytest.fixture
    def recon_context(self):
        return ReconContext(
            target_url="https://example.com",
            live_endpoints=["https://example.com/api"],
            has_api=True,
        )

    def test_plan_next_action_with_mock_llm(self, agent, recon_context):
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
        mock_llm = Mock()
        mock_llm.is_available.return_value = True
        mock_llm.chat_sync.return_value = (
            '{"tool": "__done__", "arguments": {}, "reasoning": "All tools covered"}'
        )

        action = agent.plan_next_action(
            task="scan: https://example.com",
            context="",
            recon_context=recon_context,
            llm_client=mock_llm,
        )

        assert action is None

    def test_plan_next_action_llm_unknown_tool(self, agent, recon_context):
        mock_llm = Mock()
        mock_llm.is_available.return_value = True
        mock_llm.chat_sync.return_value = (
            '{"tool": "nonexistent_tool", "arguments": {}, "reasoning": "Testing"}'
        )

        action = agent.plan_next_action(
            task="scan: https://example.com",
            context="",
            recon_context=recon_context,
            llm_client=mock_llm,
        )

        assert action is not None
        assert action.tool in ("nuclei", "dalfox")

    def test_plan_next_action_llm_exception(self, agent, recon_context):
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
        assert action.tool in ("nuclei", "dalfox")

    def test_plan_next_action_no_llm(self, agent):
        action = agent.plan_next_action(
            task="scan: https://example.com",
            context="",
        )

        assert action is not None
        assert action.tool in ("nuclei", "dalfox")

    def test_plan_next_action_all_tools_tried(self, agent):
        action = agent.plan_next_action(
            task="scan: https://example.com",
            context="",
            tried_tools={"nuclei", "dalfox"},
        )

        assert action is None


class TestPlanNextActionWithHypotheses:
    """Tests that hypotheses influence tool selection planning."""

    @pytest.fixture
    def agent(self):
        registry = ToolRegistry()
        registry.register(
            "sqlmap",
            lambda _target="", **_kw: AgentResult(
                tool="sqlmap", success=True, output="sqlmap found: id parameter injectable"
            ),
            {"name": "sqlmap", "description": "SQL injection scanner", "parameters": []},
        )
        registry.register(
            "dalfox",
            lambda _target="", **_kw: AgentResult(
                tool="dalfox", success=True, output="ok"
            ),
            {"name": "dalfox", "description": "XSS scanner", "parameters": []},
        )
        registry.register(
            "nuclei",
            lambda _target="", **_kw: AgentResult(
                tool="nuclei", success=True, output="ok"
            ),
            {"name": "nuclei", "description": "Vuln scanner", "parameters": []},
        )
        return ReActAgent(registry)

    @pytest.fixture
    def recon_context(self):
        return ReconContext(
            target_url="https://example.com",
            live_endpoints=["https://example.com/api", "https://example.com/search"],
            has_api=True,
        )

    SAMPLE_HYPOTHESES = [
        {
            "id": "hyp-sqli-001",
            "description": "SQL injection possible on /api/search parameter 'id'",
            "confidence": 0.85,
            "status": "UNVERIFIED",
            "suggested_tools": ["sqlmap", "verification_agent"],
            "verification_steps": [
                {
                    "description": "Run sqlmap to verify SQLi",
                    "tool": "sqlmap",
                    "arguments": {"target": "/api/search"},
                    "expected": "findings_count > 0",
                }
            ],
            "finding_ids": ["f-001", "f-002"],
            "supporting_finding_ids": [],
            "refuting_finding_ids": [],
        },
        {
            "id": "hyp-xss-002",
            "description": "Reflected XSS possible on search endpoint",
            "confidence": 0.65,
            "status": "UNVERIFIED",
            "suggested_tools": ["dalfox", "verification_agent"],
            "verification_steps": [
                {
                    "description": "Run dalfox to verify XSS",
                    "tool": "dalfox",
                    "arguments": {"target": "/search"},
                    "expected": "findings_count > 0",
                }
            ],
            "finding_ids": ["f-003"],
            "supporting_finding_ids": [],
            "refuting_finding_ids": [],
        },
    ]

    def test_build_tool_selection_prompt_includes_hypotheses_section(self):
        from agent.agent_prompts import build_tool_selection_prompt

        prompt = build_tool_selection_prompt(
            recon_context="Target: example.com",
            available_tools=[
                {"name": "sqlmap", "description": "SQL injection scanner"},
                {"name": "dalfox", "description": "XSS scanner"},
            ],
            tried_tools=set(),
            observation_history="",
            hypotheses=self.SAMPLE_HYPOTHESES,
        )
        assert "=== ACTIVE HYPOTHESES ===" in prompt
        assert "SQL injection possible on /api/search" in prompt
        assert "Reflected XSS possible on search" in prompt
        assert "[0.85]" in prompt
        assert "[0.65]" in prompt
        assert "verify_with=sqlmap" in prompt
        assert "verify_with=dalfox" in prompt
        assert "Prefer tools that confirm or refute" in prompt

    def test_build_tool_selection_prompt_without_hypotheses(self):
        from agent.agent_prompts import build_tool_selection_prompt

        prompt = build_tool_selection_prompt(
            recon_context="Target: example.com",
            available_tools=[{"name": "nuclei", "description": "Scanner"}],
            tried_tools=set(),
            observation_history="",
        )
        assert "=== ACTIVE HYPOTHESES ===" not in prompt
        assert "Prefer tools that confirm or refute" not in prompt

    def test_build_tool_selection_prompt_hypotheses_sorted_by_confidence(self):
        from agent.agent_prompts import build_tool_selection_prompt

        unsorted_hypotheses = [
            self.SAMPLE_HYPOTHESES[1],
            self.SAMPLE_HYPOTHESES[0],
        ]
        prompt = build_tool_selection_prompt(
            recon_context="Target: example.com",
            available_tools=[{"name": "sqlmap", "description": "SQLi"}],
            tried_tools=set(),
            observation_history="",
            hypotheses=unsorted_hypotheses,
        )
        idx_085 = prompt.index("[0.85]")
        idx_065 = prompt.index("[0.65]")
        assert idx_085 < idx_065

    def test_plan_next_action_with_hypotheses_mock_llm(self, agent, recon_context):
        mock_llm = Mock()
        mock_llm.is_available.return_value = True
        mock_llm.chat_sync.return_value = (
            '{"tool": "sqlmap", "arguments": {"target": "https://example.com"}, '
            '"reasoning": "SQLi hypothesis with highest confidence suggests sqlmap"}'
        )

        action = agent.plan_next_action(
            task="deep_scan: https://example.com",
            context="",
            recon_context=recon_context,
            llm_client=mock_llm,
            hypotheses=self.SAMPLE_HYPOTHESES,
        )

        call_args = mock_llm.chat_sync.call_args
        assert call_args is not None
        # Use str() fallback to safely extract the prompt regardless of call signature
        user_prompt = call_args[0][1] if len(call_args[0]) > 1 else str(call_args)
        assert "=== ACTIVE HYPOTHESES ===" in user_prompt
        assert "SQL injection possible on /api/search" in user_prompt
        assert "Prefer tools that confirm or refute" in user_prompt

        assert action is not None
        assert action.tool == "sqlmap"
        assert "SQLi" in action.reasoning

    def test_plan_next_action_with_hypotheses_selects_matching_tool(
        self, agent, recon_context
    ):
        mock_llm = Mock()
        mock_llm.is_available.return_value = True
        mock_llm.chat_sync.return_value = (
            '{"tool": "sqlmap", "arguments": {"target": "https://example.com"}, '
            '"reasoning": "SQLi hypothesis with confidence 0.85 recommends sqlmap"}'
        )

        action = agent.plan_next_action(
            task="deep_scan: https://example.com",
            context="",
            recon_context=recon_context,
            llm_client=mock_llm,
            hypotheses=self.SAMPLE_HYPOTHESES,
        )

        assert action is not None
        assert action.tool == "sqlmap"
        call_args = mock_llm.chat_sync.call_args
        user_prompt = call_args[0][1] if len(call_args[0]) > 1 else str(call_args)
        assert "hypotheses" in user_prompt.lower() or "ACTIVE HYPOTHESES" in user_prompt

    def test_plan_next_action_hypotheses_empty_list(self, agent, recon_context):
        mock_llm = Mock()
        mock_llm.is_available.return_value = True
        mock_llm.chat_sync.return_value = (
            '{"tool": "nuclei", "arguments": {"target": "https://example.com"}, '
            '"reasoning": "Standard scan"}'
        )

        action = agent.plan_next_action(
            task="scan: https://example.com",
            context="",
            recon_context=recon_context,
            llm_client=mock_llm,
            hypotheses=[],
        )

        assert action is not None
        call_args = mock_llm.chat_sync.call_args
        user_prompt = call_args[0][1] if len(call_args[0]) > 1 else str(call_args)
        assert "=== ACTIVE HYPOTHESES ===" not in user_prompt

    def test_plan_next_action_hypotheses_none_list(self, agent, recon_context):
        mock_llm = Mock()
        mock_llm.is_available.return_value = True
        mock_llm.chat_sync.return_value = (
            '{"tool": "nuclei", "arguments": {"target": "https://example.com"}, '
            '"reasoning": "Running nuclei first"}'
        )

        action = agent.plan_next_action(
            task="scan: https://example.com",
            context="",
            recon_context=recon_context,
            llm_client=mock_llm,
            hypotheses=None,
        )

        assert action is not None
        call_args = mock_llm.chat_sync.call_args
        user_prompt = call_args[0][1] if len(call_args[0]) > 1 else str(call_args)
        assert "=== ACTIVE HYPOTHESES ===" not in user_prompt


class TestReActAgentRunWithHypotheses:
    """End-to-end tests: agent.run() loads hypotheses from EngagementState
    and prioritizes tools matching the highest-confidence unverified hypothesis."""

    SAMPLE_HYPOTHESES = [
        {
            "id": "hyp-sqli-001",
            "description": "SQL injection possible on /api/search parameter 'id'",
            "confidence": 0.85,
            "status": "UNVERIFIED",
            "suggested_tools": ["sqlmap"],
            "verification_steps": [
                {
                    "description": "Run sqlmap to verify SQLi",
                    "tool": "sqlmap",
                    "arguments": {"target": "/api/search"},
                    "expected": "findings_count > 0",
                }
            ],
            "finding_ids": ["f-001"],
            "supporting_finding_ids": [],
            "refuting_finding_ids": [],
        },
    ]

    @pytest.fixture
    def mock_llm(self):
        m = Mock()
        m.is_available.return_value = True
        m.chat_sync.return_value = (
            '{"tool": "sqlmap", "arguments": {"target": "https://example.com"}, '
            '"reasoning": "SQLi hypothesis suggests sqlmap"}'
        )
        return m

    @pytest.fixture
    def agent(self, mock_llm):
        registry = ToolRegistry()
        registry.register(
            "sqlmap",
            lambda _target="", **_kw: AgentResult(
                tool="sqlmap", success=True, output="sqlmap found: parameter injectable"
            ),
            {"name": "sqlmap", "description": "SQL injection scanner", "parameters": []},
        )
        registry.register(
            "nuclei",
            lambda _target="", **_kw: AgentResult(
                tool="nuclei", success=True, output="ok"
            ),
            {"name": "nuclei", "description": "Vuln scanner", "parameters": []},
        )
        return ReActAgent(registry, llm_client=mock_llm)

    @pytest.fixture
    def engagement_state(self):
        from runtime.engagement_state import EngagementState

        state = EngagementState("test-eng-001")
        for h in self.SAMPLE_HYPOTHESES:
            state.add_hypothesis(dict(h))
        return state

    @pytest.fixture
    def recon_context(self):
        return ReconContext(
            target_url="https://example.com",
            live_endpoints=["https://example.com/api", "https://example.com/search"],
            has_api=True,
        )

    @patch("agent.react_agent._ff_enabled", return_value=True)
    def test_run_loads_hypotheses_and_selects_matching_tool(
        self, mock_ff, agent, engagement_state, recon_context
    ):
        """When EngagementState has active hypotheses, agent.run() loads them
        and selects the tool matching the highest-confidence hypothesis."""
        agent.engagement_state = engagement_state

        results = agent.run(
            task="deep_scan: https://example.com",
            recon_context=recon_context,
        )

        assert len(results) >= 1
        assert results[0].tool == "sqlmap"

    @patch("agent.react_agent._ff_enabled", return_value=True)
    def test_run_passes_hypotheses_to_llm_prompt(
        self, mock_ff, agent, engagement_state, recon_context
    ):
        """Verify the LLM received hypotheses in the prompt when run
        from agent.run()."""
        agent.engagement_state = engagement_state

        agent.run(
            task="deep_scan: https://example.com",
            recon_context=recon_context,
        )

        call_args = agent.llm_client.chat_sync.call_args
        assert call_args is not None
        user_prompt = call_args[0][1] if len(call_args[0]) > 1 else str(call_args)
        assert "=== ACTIVE HYPOTHESES ===" in user_prompt
        assert "SQL injection possible on /api/search" in user_prompt
        assert "Prefer tools that confirm or refute" in user_prompt

    @patch("agent.react_agent._ff_enabled", return_value=False)
    def test_run_hypothesis_flag_disabled_hides_section(
        self, mock_ff, agent, engagement_state, recon_context
    ):
        """When HYPOTHESIS_ENGINE/ENGAGEMENT_STATE flags are disabled,
        no hypothesis section appears in the LLM prompt."""
        agent.engagement_state = engagement_state

        agent.run(
            task="deep_scan: https://example.com",
            recon_context=recon_context,
        )

        call_args = agent.llm_client.chat_sync.call_args
        assert call_args is not None
        user_prompt = call_args[0][1] if len(call_args[0]) > 1 else str(call_args)
        assert "=== ACTIVE HYPOTHESES ===" not in user_prompt

    @patch("agent.react_agent._ff_enabled", return_value=True)
    def test_run_without_engagement_state_skips_hypotheses(
        self, mock_ff, agent, recon_context
    ):
        """When no engagement_state is set, agent.run() runs normally
        without hypotheses."""
        agent.engagement_state = None

        results = agent.run(
            task="deep_scan: https://example.com",
            recon_context=recon_context,
        )

        assert len(results) >= 1
        call_args = agent.llm_client.chat_sync.call_args
        assert call_args is not None
        user_prompt = call_args[0][1] if len(call_args[0]) > 1 else str(call_args)
        assert "=== ACTIVE HYPOTHESES ===" not in user_prompt


class TestUpdateHypothesesFromResult:
    """Tests for _update_hypotheses_from_result() — confidence/status transitions."""

    CONFIRMED_HYPOTHESIS = {
        "id": "hyp-sqli-090",
        "description": "SQL injection on /api/search with confidence 0.9",
        "confidence": 0.9,
        "status": "UNVERIFIED",
        "suggested_tools": ["sqlmap"],
        "finding_ids": ["f-001"],
        "supporting_finding_ids": [],
        "refuting_finding_ids": [],
    }

    @pytest.fixture
    def agent(self):
        registry = ToolRegistry()
        return ReActAgent(registry)

    @pytest.fixture
    def engagement_state(self):
        from runtime.engagement_state import EngagementState

        state = EngagementState("test-eng-confirmed")
        state.add_hypothesis(dict(self.CONFIRMED_HYPOTHESIS))
        return state

    @patch("database.repositories.hypothesis_repository.HypothesisRepository.update")
    def test_positive_result_transitions_status_to_confirmed(
        self, mock_update, agent, engagement_state
    ):
        """Start with confidence 0.9, call _update_hypotheses_from_result with
        a matching successful result that has findings. Expect:
        - confidence → 1.0 (capped from 0.9 + 0.1)
        - status → "CONFIRMED" (since 1.0 >= 0.85)
        - supporting_finding_ids contains the result finding ID."""
        agent.engagement_state = engagement_state

        result = AgentResult(
            tool="sqlmap",
            success=True,
            output="sqlmap found: parameter id injectable",
            findings=[{"id": "f-finding-001"}],
        )

        agent._update_hypotheses_from_result("sqlmap", result)

        # Verify Postgres was called
        mock_update.assert_called_once()

        # Verify in-memory state updated
        updated = engagement_state.hypotheses[0]
        assert updated["confidence"] == 1.0
        assert updated["status"] == "CONFIRMED"
        assert "f-finding-001" in updated["supporting_finding_ids"]

    @patch("database.repositories.hypothesis_repository.HypothesisRepository.update")
    def test_positive_result_confidence_below_threshold_stays_unverified(
        self, mock_update, agent, engagement_state
    ):
        """Start with confidence 0.7, positive result brings it to 0.8
        which is still below 0.85 → status stays UNVERIFIED."""
        engagement_state.hypotheses[0]["confidence"] = 0.7
        engagement_state.hypotheses[0]["status"] = "UNVERIFIED"
        agent.engagement_state = engagement_state

        result = AgentResult(
            tool="sqlmap",
            success=True,
            output="no obvious SQLi detected",
            findings=[{"id": "f-finding-002"}],
        )

        agent._update_hypotheses_from_result("sqlmap", result)

        updated = engagement_state.hypotheses[0]
        assert updated["confidence"] == pytest.approx(0.8)  # 0.7 + 0.1
        assert updated["status"] == "UNVERIFIED"  # 0.8 < 0.85


class TestReActAgentRun:
    @pytest.fixture
    def agent(self):
        registry = ToolRegistry()
        registry.register(
            "nuclei",
            lambda _target="", **_kw: AgentResult(
                tool="nuclei", success=True, output="ok"
            ),
            {"name": "nuclei", "description": "Vuln scanner", "parameters": []},
        )
        return ReActAgent(registry, max_iterations=5)

    def test_run_respects_max_iterations(self, agent):
        results = agent.run("scan: https://example.com")
        assert len(results) <= 5

    def test_run_returns_agent_results(self, agent):
        results = agent.run("scan: https://example.com")
        for r in results:
            assert isinstance(r, AgentResult)
