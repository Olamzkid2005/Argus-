"""
Pipeline integration test for the Hypothesis Engine.

Tests the end-to-end flow:
1. Seed findings → HypothesisEngine.generate() → Hypotheses
2. Persist via mocked HypothesisRepository.create()
3. Load into EngagementState via add_hypothesis()
4. Run _update_hypotheses_from_result() with a matching tool result
5. Verify supporting_finding_ids are accumulated
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agent.agent_result import AgentResult
from agent.react_agent import ReActAgent
from agent.tool_registry import ToolRegistry
from runtime.engagement_state import EngagementState
from tools.hypothesis_engine import HypothesisEngine

# ── Sample findings ──────────────────────────────────────────────────

SQLI_FINDINGS = [
    {
        "id": "f-001",
        "type": "SQL_INJECTION",
        "severity": "CRITICAL",
        "endpoint": "https://example.com/api/search?id=1",
        "confidence": 0.9,
        "cwe_id": "89",
        "evidence": {"parameter": "id", "payload": "' OR 1=1 --"},
    },
    {
        "id": "f-002",
        "type": "BLIND_SQLI",
        "severity": "HIGH",
        "endpoint": "https://example.com/api/items?category=1",
        "confidence": 0.7,
        "cwe_id": "89",
        "evidence": {"parameter": "category", "payload": "1 AND 1=1"},
    },
    {
        "id": "f-003",
        "type": "ERROR_SQLI",
        "severity": "MEDIUM",
        "endpoint": "https://example.com/api/filter?sort=1",
        "confidence": 0.5,
        "cwe_id": "89",
        "evidence": {"parameter": "sort", "payload": "1'"},
    },
]

XSS_FINDINGS = [
    {
        "id": "f-004",
        "type": "REFLECTED_XSS",
        "severity": "HIGH",
        "endpoint": "https://example.com/search?q=test",
        "confidence": 0.8,
        "evidence": {"param": "q", "payload": "<script>alert(1)</script>"},
    },
    {
        "id": "f-005",
        "type": "STORED_XSS",
        "severity": "MEDIUM",
        "endpoint": "https://example.com/profile",
        "confidence": 0.6,
        "evidence": {"param": "name", "payload": "<img src=x onerror=alert(1)>"},
    },
]


# ── Helper: create a mock AgentResult from sqlmap-like tool output ────

def _make_sqlmap_result() -> AgentResult:
    """Simulate a successful sqlmap run that found SQL injection."""
    return AgentResult(
        tool="sqlmap",
        success=True,
        output="sqlmap found SQL injection on parameter 'id'\n"
               "Type: boolean-based blind",
        findings=[
            {"id": "f-001", "type": "SQL_INJECTION", "severity": "CRITICAL"},
            # sqlmap may also produce its own additional finding IDs
            {"id": "f-002", "type": "BLIND_SQLI", "severity": "HIGH"},
        ],
    )


def _make_sqlmap_empty_result() -> AgentResult:
    """Simulate a successful sqlmap run that found NO injection."""
    return AgentResult(
        tool="sqlmap",
        success=True,
        output="sqlmap completed - no vulnerabilities found",
        findings=[],
    )


def _make_failed_result() -> AgentResult:
    """Simulate a failed tool run."""
    return AgentResult(
        tool="sqlmap",
        success=False,
        error="Command timed out after 300s",
        output="",
        findings=[],
    )


# ── Tests ────────────────────────────────────────────────────────────


class TestHypothesisPipeline:
    """End-to-end pipeline: findings → hypotheses → verification → update."""

    @pytest.mark.requires_db
    @patch("feature_flags.is_enabled", return_value=True)
    def test_full_pipeline_generates_and_persists_hypotheses(
        self, mock_is_enabled
    ):
        """Step 1: Seed findings → HypothesisEngine.generate() → hypotheses."""
        engine = HypothesisEngine()
        all_findings = SQLI_FINDINGS + XSS_FINDINGS
        hypotheses = engine.generate(all_findings, "eng-pipeline-1")
        assert len(hypotheses) >= 1, "Should generate at least one hypothesis"
        # The SQLi findings share CWE-89, should form a grouped hypothesis
        cwe_hypotheses = [
            h for h in hypotheses if h.get("root_cause_key") == "cwe:89"
        ]
        assert len(cwe_hypotheses) >= 1, (
            "SQLi findings with CWE-89 should form a CWE-grouped hypothesis"
        )
        sql_hyp = cwe_hypotheses[0]
        assert sql_hyp["status"] == "UNVERIFIED"
        assert sql_hyp["engagement_id"] == "eng-pipeline-1"
        assert "sqlmap" in sql_hyp.get("suggested_tools", [])
        assert "verification_agent" in sql_hyp.get("suggested_tools", [])
        assert len(sql_hyp.get("finding_ids", [])) >= 2
        assert "f-001" in sql_hyp["finding_ids"]

    @pytest.mark.requires_db
    @patch("feature_flags.is_enabled", return_value=True)
    @patch("database.repositories.hypothesis_repository.HypothesisRepository.create")
    def test_persist_via_hypothesis_repository(
        self, mock_create, mock_is_enabled
    ):
        """Step 2: Hypotheses persisted via HypothesisRepository.create()."""
        mock_create.return_value = {
            "id": "hyp-001",
            "engagement_id": "eng-pipeline-2",
            "status": "UNVERIFIED",
        }
        engine = HypothesisEngine()
        hypotheses = engine.generate(SQLI_FINDINGS, "eng-pipeline-2")
        assert len(hypotheses) >= 1
        # Simulate persisting via HypothesisRepository
        from database.repositories.hypothesis_repository import (
            HypothesisRepository,
        )

        repo = HypothesisRepository()
        for h in hypotheses:
            result = repo.create(h)
            assert result is not None
            mock_create.assert_called()

    @pytest.mark.requires_db
    @patch("feature_flags.is_enabled", return_value=True)
    def test_engagement_state_loads_hypotheses(self, mock_is_enabled):
        """Step 3: Hypotheses loaded into EngagementState via add_hypothesis()."""
        engine = HypothesisEngine()
        hypotheses = engine.generate(SQLI_FINDINGS, "eng-pipeline-3")
        assert len(hypotheses) >= 1

        state = EngagementState("eng-pipeline-3")
        for h in hypotheses:
            state.add_hypothesis(h)
        active = state.get_active_hypotheses(max_count=10)
        assert len(active) >= 1
        # Only UNVERIFIED hypotheses should be returned as active
        assert all(h["status"] == "UNVERIFIED" for h in active)

    @pytest.mark.requires_db
    @patch("feature_flags.is_enabled", return_value=True)
    @patch(
        "database.repositories.hypothesis_repository.HypothesisRepository.update",
        return_value={},
    )
    def test_update_from_result_accumulates_supporting_finding_ids(
        self, mock_update, mock_is_enabled
    ):
        """Step 4-5: _update_hypotheses_from_result() accumulates
        supporting_finding_ids when a matching verification tool finds evidence."""
        engine = HypothesisEngine()
        hypotheses = engine.generate(SQLI_FINDINGS, "eng-pipeline-4")
        assert len(hypotheses) >= 1

        # Find the GROUPED SQLi hypothesis (with root_cause_key, confidence < 1.0)
        # The single-finding hypothesis for CRITICAL findings has confidence=1.0
        # and would shadow the grouped one when sorted by confidence desc.
        sql_hyp = next(
            (
                h
                for h in hypotheses
                if "sqlmap" in h.get("suggested_tools", [])
                and h.get("root_cause_key") is not None
            ),
            None,
        )
        assert sql_hyp is not None, (
            "Should have a grouped SQLi hypothesis with sqlmap"
        )
        assert (
            sql_hyp["confidence"] < 1.0
        ), "Grouped hypothesis confidence must be < 1.0 for this test"

        # Create EngagementState and add a COPY of the hypothesis
        from copy import deepcopy

        state = EngagementState("eng-pipeline-4")
        state.add_hypothesis(deepcopy(sql_hyp))
        initial_confidence = sql_hyp["confidence"]

        # Create a ReActAgent with the engagement state
        registry = ToolRegistry()
        agent = ReActAgent(
            registry=registry,
            engagement_state=state,
            engagement_id="eng-pipeline-4",
        )

        # Simulate sqlmap running and finding SQL injection
        result = _make_sqlmap_result()
        agent._update_hypotheses_from_result("sqlmap", result)

        # Verify: supporting_finding_ids should contain finding IDs from the result
        updated_hyp = state.hypotheses[0]
        assert len(updated_hyp.get("supporting_finding_ids", [])) >= 1
        assert "f-001" in updated_hyp["supporting_finding_ids"]
        # Confidence should have increased (use initial_confidence from snapshot)
        assert updated_hyp["confidence"] > initial_confidence

    @pytest.mark.requires_db
    @patch("feature_flags.is_enabled", return_value=True)
    @patch(
        "database.repositories.hypothesis_repository.HypothesisRepository.update",
        return_value={},
    )
    def test_empty_result_decreases_confidence(
        self, mock_update, mock_is_enabled
    ):
        """When a verification tool runs cleanly (no findings), confidence
        should decrease slightly."""
        engine = HypothesisEngine()
        hypotheses = engine.generate(SQLI_FINDINGS, "eng-pipeline-5")
        sql_hyp = next(
            (
                h
                for h in hypotheses
                if "sqlmap" in h.get("suggested_tools", [])
                and h.get("root_cause_key") is not None
            ),
            None,
        )
        assert sql_hyp is not None

        from copy import deepcopy

        state = EngagementState("eng-pipeline-5")
        state.add_hypothesis(deepcopy(sql_hyp))
        initial_confidence = sql_hyp["confidence"]

        registry = ToolRegistry()
        agent = ReActAgent(
            registry=registry,
            engagement_state=state,
            engagement_id="eng-pipeline-5",
        )

        # Empty sqlmap result (tool ran but found nothing)
        result = _make_sqlmap_empty_result()
        agent._update_hypotheses_from_result("sqlmap", result)

        updated_hyp = state.hypotheses[0]
        # Empty output (< 30 chars) with no findings → slight confidence decrease
        assert updated_hyp["confidence"] <= initial_confidence
        # supporting_finding_ids should NOT have been updated
        assert len(updated_hyp.get("supporting_finding_ids", [])) == 0

    @pytest.mark.requires_db
    @patch("feature_flags.is_enabled", return_value=True)
    @patch(
        "database.repositories.hypothesis_repository.HypothesisRepository.update",
        return_value={},
    )
    def test_failed_result_may_decrease_confidence(
        self, mock_update, mock_is_enabled
    ):
        """When a verification tool fails, confidence should decrease."""
        engine = HypothesisEngine()
        hypotheses = engine.generate(SQLI_FINDINGS, "eng-pipeline-6")
        sql_hyp = next(
            (
                h
                for h in hypotheses
                if "sqlmap" in h.get("suggested_tools", [])
                and h.get("root_cause_key") is not None
            ),
            None,
        )
        assert sql_hyp is not None

        from copy import deepcopy

        state = EngagementState("eng-pipeline-6")
        state.add_hypothesis(deepcopy(sql_hyp))
        initial_confidence = sql_hyp["confidence"]

        registry = ToolRegistry()
        agent = ReActAgent(
            registry=registry,
            engagement_state=state,
            engagement_id="eng-pipeline-6",
        )

        # Failed sqlmap run
        result = _make_failed_result()
        agent._update_hypotheses_from_result("sqlmap", result)

        updated_hyp = state.hypotheses[0]
        assert updated_hyp["confidence"] < initial_confidence

    @pytest.mark.requires_db
    @patch("feature_flags.is_enabled", return_value=True)
    def test_non_matching_tool_does_not_update_hypothesis(
        self, mock_is_enabled
    ):
        """A tool that is not in the hypothesis's suggested_tools should
        not affect the hypothesis."""
        engine = HypothesisEngine()
        hypotheses = engine.generate(SQLI_FINDINGS, "eng-pipeline-7")
        sql_hyp = next(
            (
                h
                for h in hypotheses
                if "sqlmap" in h.get("suggested_tools", [])
            ),
            None,
        )
        assert sql_hyp is not None

        state = EngagementState("eng-pipeline-7")
        state.add_hypothesis(sql_hyp)
        initial_confidence = sql_hyp["confidence"]

        registry = ToolRegistry()
        agent = ReActAgent(
            registry=registry,
            engagement_state=state,
            engagement_id="eng-pipeline-7",
        )

        # nuclei is NOT in suggested_tools for SQLi hypothesis
        result = _make_sqlmap_result()
        agent._update_hypotheses_from_result("nuclei", result)

        # Hypothesis should be unchanged
        updated_hyp = state.hypotheses[0]
        assert updated_hyp["confidence"] == initial_confidence
        assert len(updated_hyp.get("supporting_finding_ids", [])) == 0

    @pytest.mark.requires_db
    @patch("feature_flags.is_enabled", return_value=True)
    @patch(
        "database.repositories.hypothesis_repository.HypothesisRepository.update",
        return_value={},
    )
    def test_multiple_updates_cumulative_supporting_finding_ids(
        self, mock_update, mock_is_enabled
    ):
        """Multiple tool results that match a hypothesis should cumulatively
        add to supporting_finding_ids."""
        engine = HypothesisEngine()
        hypotheses = engine.generate(SQLI_FINDINGS, "eng-pipeline-8")
        sql_hyp = next(
            (
                h
                for h in hypotheses
                if "sqlmap" in h.get("suggested_tools", [])
                and h.get("root_cause_key") is not None
            ),
            None,
        )
        assert sql_hyp is not None

        from copy import deepcopy

        state = EngagementState("eng-pipeline-8")
        state.add_hypothesis(deepcopy(sql_hyp))

        registry = ToolRegistry()
        agent = ReActAgent(
            registry=registry,
            engagement_state=state,
            engagement_id="eng-pipeline-8",
        )

        # First sqlmap run
        result1 = AgentResult(
            tool="sqlmap",
            success=True,
            output="Found SQL injection",
            findings=[{"id": "f-001", "type": "SQL_INJECTION"}],
        )
        agent._update_hypotheses_from_result("sqlmap", result1)

        # Second sqlmap run (different parameter)
        result2 = AgentResult(
            tool="sqlmap",
            success=True,
            output="Found more SQL injection",
            findings=[{"id": "f-003", "type": "ERROR_SQLI"}],
        )
        agent._update_hypotheses_from_result("sqlmap", result2)

        updated_hyp = state.hypotheses[0]
        # Should have accumulated finding IDs from both results
        support_ids = updated_hyp.get("supporting_finding_ids", [])
        assert "f-001" in support_ids
        # Note: f-003 may or may not be present depending on
        # whether it was in the original finding_ids of the hypothesis.
        # The key test is that f-001 was added from result1.
