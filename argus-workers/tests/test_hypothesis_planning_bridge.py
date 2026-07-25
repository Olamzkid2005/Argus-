"""Tests for hypothesis_planning_bridge.py — Hypothesis-to-Phase activation bridge."""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from orchestrator_pkg.planning.adaptive_planner import (
    WorkflowPlan,
    TestingPhase,
    ToolTask,
)


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def empty_plan() -> WorkflowPlan:
    """A plan with no phases."""
    return WorkflowPlan(
        phases=[],
        total_phases=0,
        activated_phases=0,
        skipped_phases=[],
        target_url="https://example.com",
        summary="Test plan",
    )


@pytest.fixture
def populated_plan() -> WorkflowPlan:
    """A plan with two existing phases."""
    return WorkflowPlan(
        phases=[
            TestingPhase(
                name="auth_testing",
                description="Authentication testing",
                activation_reason="login page detected",
                order=10,
                tools=[
                    ToolTask(
                        tool_name="nuclei",
                        description="Auth scanning",
                        priority=10,
                        timeout=300,
                        args_template=["-u", "{target}", "-tags", "auth"],
                    ),
                ],
            ),
            TestingPhase(
                name="api_scan",
                description="API scanning",
                activation_reason="API endpoints found",
                order=20,
                tools=[
                    ToolTask(
                        tool_name="nuclei",
                        description="API scanning",
                        priority=10,
                        timeout=300,
                        args_template=["-u", "{target}", "-tags", "api"],
                    ),
                ],
            ),
        ],
        total_phases=2,
        activated_phases=2,
        skipped_phases=[],
        target_url="https://example.com",
        summary="Plan with existing phases",
    )


@pytest.fixture
def sql_injection_hypothesis() -> dict:
    return {
        "suggested_tools": ["sqlmap"],
        "confidence": 0.85,
        "root_cause_key": "cwe:89",
        "description": "SQL injection cluster detected on login endpoint",
        "finding_ids": ["f1", "f2"],
    }


@pytest.fixture
def ssrf_hypothesis() -> dict:
    return {
        "suggested_tools": ["ssrf"],
        "confidence": 0.75,
        "root_cause_key": "cwe:918",
        "description": "SSRF detected via callback parameter",
        "finding_ids": ["f3"],
    }


@pytest.fixture
def jwt_hypothesis() -> dict:
    return {
        "suggested_tools": ["jwt_tool"],
        "confidence": 0.7,
        "root_cause_key": "jwt",
        "description": "JWT weaknesses detected in auth tokens",
        "finding_ids": ["f4", "f5"],
    }


@pytest.fixture
def low_confidence_hypothesis() -> dict:
    return {
        "suggested_tools": ["nuclei"],
        "confidence": 0.3,
        "root_cause_key": "low_confidence",
        "description": "Low confidence test — should be skipped",
        "finding_ids": [],
    }


@pytest.fixture
def empty_tools_hypothesis() -> dict:
    return {
        "suggested_tools": [],
        "confidence": 0.9,
        "root_cause_key": "empty_tools",
        "description": "No tools suggested — should be skipped",
        "finding_ids": [],
    }


# =========================================================================
# _match_hypothesis_to_phases tests
# =========================================================================


class TestMatchHypothesisToPhases:
    """Test the internal mapping function."""

    def test_import(self):
        """Module imports correctly."""
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            _match_hypothesis_to_phases,
            update_plan_from_hypotheses,
            apply_hypothesis_engine,
            _HYPOTHESIS_PHASE_MAP,
        )
        assert len(_HYPOTHESIS_PHASE_MAP) >= 50, (
            f"Expected 50+ map entries, got {len(_HYPOTHESIS_PHASE_MAP)}"
        )

    def test_sqlmap_tool_maps_to_input_validation(self):
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            _match_hypothesis_to_phases,
        )
        hyp = {"suggested_tools": ["sqlmap"], "confidence": 0.9,
               "root_cause_key": "cwe:89", "description": "SQLi"}
        phases = _match_hypothesis_to_phases(hyp)
        assert "input_validation" in phases

    def test_jwt_tool_maps_to_session_analysis(self):
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            _match_hypothesis_to_phases,
        )
        hyp = {"suggested_tools": ["jwt_tool"], "confidence": 0.7,
               "root_cause_key": "jwt", "description": "JWT weaknesses"}
        phases = _match_hypothesis_to_phases(hyp)
        assert "session_analysis" in phases

    def test_ssrf_maps_to_ssrf_testing(self):
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            _match_hypothesis_to_phases,
        )
        hyp = {"suggested_tools": ["ssrf"], "confidence": 0.8,
               "root_cause_key": "cwe:918", "description": "SSRF"}
        phases = _match_hypothesis_to_phases(hyp)
        assert "ssrf_testing" in phases

    def test_cwe_key_matches_without_tools(self):
        """CWE key in root_cause_key should match even without suggested_tools."""
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            _match_hypothesis_to_phases,
        )
        hyp = {"suggested_tools": [], "confidence": 0.8,
               "root_cause_key": "cwe:89", "description": "SQLi via CWE key"}
        phases = _match_hypothesis_to_phases(hyp)
        assert "input_validation" in phases

    def test_description_keyword_fallback(self):
        """No tools or CWE key, but description contains keyword."""
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            _match_hypothesis_to_phases,
        )
        hyp = {"suggested_tools": [], "confidence": 0.8,
               "root_cause_key": "unknown", "description": "xss vulnerability cluster"}
        phases = _match_hypothesis_to_phases(hyp)
        assert "input_validation" in phases

    def test_empty_suggested_tools_returns_empty(self):
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            _match_hypothesis_to_phases,
        )
        hyp = {"suggested_tools": [], "confidence": 0.8,
               "root_cause_key": "unknown", "description": "No tools"}
        phases = _match_hypothesis_to_phases(hyp)
        assert len(phases) == 0

    def test_all_cwe_mappings(self):
        """Verify all CWE-based mappings produce correct phases."""
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            _match_hypothesis_to_phases,
        )

        cwe_to_expected = {
            "cwe:89": "input_validation", "cwe:79": "input_validation",
            "cwe:918": "ssrf_testing", "cwe:78": "ssrf_testing",
            "cwe:287": "auth_testing",
            "cwe:502": "deserialization_testing", "cwe:94": "template_injection",
            "cwe:22": "path_traversal_testing", "cwe:611": "xxe_testing",
            "cwe:601": "open_redirect_testing", "cwe:639": "access_control",
            "cwe:200": "infrastructure_testing", "cwe:942": "cors_testing",
            "cwe:352": "csrf_testing", "cwe:434": "file_upload_testing",
        }
        for cwe, expected_phase in cwe_to_expected.items():
            hyp = {"suggested_tools": [], "confidence": 0.8,
                   "root_cause_key": cwe, "description": f"Test {cwe}"}
            phases = _match_hypothesis_to_phases(hyp)
            assert expected_phase in phases, (
                f"CWE {cwe} should map to {expected_phase}, got {phases}"
            )

    def test_all_tool_mappings(self):
        """Verify all tool-based mappings produce correct phases."""
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            _match_hypothesis_to_phases,
        )

        tool_to_expected = {
            "sqlmap": "input_validation", "dalfox": "input_validation",
            "jwt_tool": "session_analysis", "dual_auth_scanner": "auth_testing",
            "introspection": "graphql_introspection",
            "graphql": "graphql_introspection",
            "cors": "cors_testing", "csrf": "csrf_testing",
            "xxe": "xxe_testing", "websocket": "websocket_testing",
            "bopla": "access_control", "idor": "access_control",
            "bola": "access_control",
            "ssti": "template_injection",
            "pickle": "deserialization_testing", "jackson": "deserialization_testing",
            "rate_limit": "rate_limit_testing",
            "swagger": "api_scan", "openapi": "api_scan",
            "file_upload": "file_upload_testing",
            "exposure": "infrastructure_testing",
        }
        for tool, expected_phase in tool_to_expected.items():
            hyp = {"suggested_tools": [tool], "confidence": 0.8,
                   "root_cause_key": "test", "description": f"Tool {tool}"}
            phases = _match_hypothesis_to_phases(hyp)
            assert expected_phase in phases, (
                f"Tool '{tool}' should map to {expected_phase}, got {phases}"
            )


# =========================================================================
# update_plan_from_hypotheses tests
# =========================================================================


class TestUpdatePlanFromHypotheses:
    """Test the core function that mutates WorkflowPlan in-place."""

    def test_empty_hypotheses_noop(self, empty_plan):
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            update_plan_from_hypotheses,
        )
        update_plan_from_hypotheses(empty_plan, [])
        assert len(empty_plan.phases) == 0
        assert empty_plan.activated_phases == 0
        assert empty_plan.total_phases == 0

    def test_none_plan_noop(self):
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            update_plan_from_hypotheses,
        )
        # Should not crash
        update_plan_from_hypotheses(None, [{"suggested_tools": ["sqlmap"], "confidence": 0.9}])

    def test_low_confidence_skipped(self, empty_plan):
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            update_plan_from_hypotheses,
        )
        hypotheses = [
            {"suggested_tools": ["sqlmap"], "confidence": 0.3,
             "root_cause_key": "low", "description": "Low confidence"},
        ]
        update_plan_from_hypotheses(empty_plan, hypotheses)
        assert len(empty_plan.phases) == 0
        assert empty_plan.activated_phases == 0
        assert empty_plan.total_phases == 0

    def test_activates_new_phases(
        self,
        empty_plan,
        sql_injection_hypothesis,
        ssrf_hypothesis,
        jwt_hypothesis,
    ):
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            update_plan_from_hypotheses,
        )
        hypotheses = [sql_injection_hypothesis, ssrf_hypothesis, jwt_hypothesis]
        update_plan_from_hypotheses(empty_plan, hypotheses)

        assert len(empty_plan.phases) == 3, f"Expected 3 phases, got {len(empty_plan.phases)}"
        assert empty_plan.activated_phases == 3
        assert empty_plan.total_phases == 3

        phase_names = [p.name for p in empty_plan.phases]
        assert "input_validation" in phase_names
        assert "ssrf_testing" in phase_names
        assert "session_analysis" in phase_names

    def test_phases_have_tools_and_hypothesis_reason(self, empty_plan, sql_injection_hypothesis):
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            update_plan_from_hypotheses,
        )
        update_plan_from_hypotheses(empty_plan, [sql_injection_hypothesis])

        phase = empty_plan.phases[0]
        assert len(phase.tools) > 0
        assert "hypothesis" in phase.activation_reason.lower()
        assert "cwe:89" in phase.activation_reason
        assert "85%" in phase.activation_reason  # 0.85 confidence

    def test_existing_phase_annotated_not_duplicated(
        self,
        populated_plan,
        sql_injection_hypothesis,
        ssrf_hypothesis,
        jwt_hypothesis,
    ):
        """Existing phases should be annotated, not duplicated."""
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            update_plan_from_hypotheses,
        )

        # Make a hypothesis that maps to api_scan (already active)
        api_hypothesis = {
            "suggested_tools": ["openapi"],
            "confidence": 0.8,
            "root_cause_key": "api_key_weakness",
            "description": "API key weakness detected",
        }

        hypotheses = [api_hypothesis, ssrf_hypothesis, jwt_hypothesis]
        initial_count = len(populated_plan.phases)
        update_plan_from_hypotheses(populated_plan, hypotheses)

        # Should have 2 existing + 2 new = 4 total (api_scan already exists)
        assert len(populated_plan.phases) == 4, (
            f"Expected 4 phases (2 existing + 2 new), got {len(populated_plan.phases)}"
        )
        assert populated_plan.activated_phases == 4
        assert populated_plan.total_phases == 4

        # Verify api_scan was annotated, not duplicated
        api_phases = [p for p in populated_plan.phases if p.name == "api_scan"]
        assert len(api_phases) == 1, "api_scan should not be duplicated!"
        assert "hypothesis" in api_phases[0].activation_reason

    def test_coverage_report_accurate(self, empty_plan, sql_injection_hypothesis, ssrf_hypothesis):
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            update_plan_from_hypotheses,
        )
        update_plan_from_hypotheses(empty_plan, [sql_injection_hypothesis, ssrf_hypothesis])

        report = empty_plan.get_coverage_report()
        assert report["activated_count"] == 2
        assert report["total_phases"] == 2
        assert report["coverage_pct"] == 1.0  # All activated

    def test_mixed_confidence_hypotheses(self, empty_plan):
        """High confidence activates, low confidence is skipped."""
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            update_plan_from_hypotheses,
        )
        hypotheses = [
            {"suggested_tools": ["sqlmap"], "confidence": 0.85,
             "root_cause_key": "high", "description": "High confidence"},
            {"suggested_tools": ["sqlmap"], "confidence": 0.3,
             "root_cause_key": "low", "description": "Low confidence"},
            {"suggested_tools": ["jwt_tool"], "confidence": 0.6,
             "root_cause_key": "medium", "description": "Medium confidence"},
        ]
        update_plan_from_hypotheses(empty_plan, hypotheses)
        # Should activate 2 (0.85 and 0.6), skip 1 (0.3)
        assert empty_plan.activated_phases == 2
        assert empty_plan.total_phases == 2

    def test_phase_order_is_200(self, empty_plan, sql_injection_hypothesis):
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            update_plan_from_hypotheses,
        )
        update_plan_from_hypotheses(empty_plan, [sql_injection_hypothesis])
        assert empty_plan.phases[0].order == 200


# =========================================================================
# _activate_phase tests
# =========================================================================


class TestActivatePhase:
    """Test that each phase type builds correct TestingPhase objects."""

    @pytest.mark.parametrize("phase_name,expected_tool_count", [
        ("input_validation", 2),
        ("ssrf_testing", 1),
        ("auth_testing", 1),
        ("session_analysis", 1),
        ("access_control", 1),
        ("deserialization_testing", 1),
        ("template_injection", 1),
        ("path_traversal_testing", 1),
        ("xxe_testing", 1),
        ("open_redirect_testing", 1),
        ("cors_testing", 1),
        ("csrf_testing", 1),
        ("rate_limit_testing", 1),
        ("websocket_testing", 1),
        ("graphql_introspection", 1),
        ("api_scan", 1),
        ("file_upload_testing", 1),
        ("infrastructure_testing", 1),
    ])
    def test_phase_activation(self, empty_plan, phase_name, expected_tool_count):
        """All 18 phase types produce valid TestingPhase with tools."""
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            _activate_phase,
        )
        hypothesis = {
            "suggested_tools": ["sqlmap"],
            "confidence": 0.8,
            "root_cause_key": "test",
            "description": f"Test activating {phase_name}",
        }
        _activate_phase(empty_plan, phase_name, hypothesis)

        assert len(empty_plan.phases) == 1
        phase = empty_plan.phases[0]
        assert phase.name == phase_name
        assert len(phase.tools) == expected_tool_count
        assert "hypothesis" in phase.activation_reason
        assert "test" in phase.activation_reason
        assert isinstance(phase.tools[0], ToolTask)

    def test_unknown_phase_raises_value_error(self, empty_plan):
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            _activate_phase,
        )
        with pytest.raises(ValueError, match="Unknown hypothesis-driven phase"):
            _activate_phase(empty_plan, "nonexistent_phase", {"confidence": 0.8})


# =========================================================================
# apply_hypothesis_engine integration tests
# =========================================================================


class TestApplyHypothesisEngine:
    """Test the one-call convenience function."""

    def test_import_error_graceful(self, empty_plan):
        """If HypothesisEngine import fails, return empty list."""
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            apply_hypothesis_engine,
        )
        with patch.dict("sys.modules", {"tools.hypothesis_engine": None}):
            result = apply_hypothesis_engine(empty_plan, [], "eng-123")
        assert result == []

    def test_generates_and_integrates_hypotheses(self, empty_plan):
        """Mock HypothesisEngine generates hypotheses, bridge integrates them."""
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            apply_hypothesis_engine,
        )
        mock_hypotheses = [
            {
                "suggested_tools": ["sqlmap"],
                "confidence": 0.85,
                "root_cause_key": "cwe:89",
                "description": "SQLi cluster",
                "finding_ids": ["f1", "f2"],
                "id": "h1",
                "status": "UNVERIFIED",
                "verification_steps": [],
            },
        ]
        mock_engine = MagicMock()
        mock_engine.generate.return_value = mock_hypotheses

        with patch(
            "tools.hypothesis_engine.HypothesisEngine",
            return_value=mock_engine,
        ):
            result = apply_hypothesis_engine(empty_plan, [{"type": "XSS", "severity": "HIGH"}], "eng-123")

        assert len(result) == 1
        assert result[0]["root_cause_key"] == "cwe:89"
        # Verify phase was activated
        assert len(empty_plan.phases) >= 1
        assert "input_validation" in [p.name for p in empty_plan.phases]

    def test_empty_findings_no_crash(self, empty_plan):
        """Empty findings list should not crash."""
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            apply_hypothesis_engine,
        )
        mock_engine = MagicMock()
        mock_engine.generate.return_value = []

        with patch(
            "tools.hypothesis_engine.HypothesisEngine",
            return_value=mock_engine,
        ):
            result = apply_hypothesis_engine(empty_plan, [], "eng-123")
        assert result == []


# =========================================================================
# Edge cases
# =========================================================================


class TestEdgeCases:
    """Edge case tests for the bridge module."""

    def test_multiple_hypotheses_same_phase_no_duplicate(self, empty_plan):
        """Two hypotheses both mapping to same phase should not create duplicates."""
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            update_plan_from_hypotheses,
        )
        hypotheses = [
            {"suggested_tools": ["sqlmap"], "confidence": 0.85,
             "root_cause_key": "cwe:89", "description": "SQLi via tool"},
            {"suggested_tools": ["dalfox"], "confidence": 0.8,
             "root_cause_key": "xss", "description": "XSS via tool"},
        ]
        update_plan_from_hypotheses(empty_plan, hypotheses)
        assert len(empty_plan.phases) == 1, (
            f"Both map to input_validation — should only be 1 phase, got "
            f"{[p.name for p in empty_plan.phases]}"
        )
        assert empty_plan.activated_phases == 1
        assert empty_plan.total_phases == 1

    def test_nested_tool_names_in_description(self, empty_plan):
        """Keywords in description should be matched."""
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            update_plan_from_hypotheses,
        )
        hyp = {
            "suggested_tools": [],
            "confidence": 0.8,
            "root_cause_key": "manual_review",
            "description": "Multiple endpoints show cors misconfiguration patterns",
        }
        update_plan_from_hypotheses(empty_plan, [hyp])
        assert empty_plan.activated_phases >= 1
        assert "cors_testing" in [p.name for p in empty_plan.phases]

    def test_tool_task_dataclass_usage(self, empty_plan, sql_injection_hypothesis):
        """Activated phases should contain proper ToolTask instances."""
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            update_plan_from_hypotheses,
        )
        update_plan_from_hypotheses(empty_plan, [sql_injection_hypothesis])

        phase = empty_plan.phases[0]
        for tool in phase.tools:
            assert isinstance(tool, ToolTask)
            assert tool.tool_name in ("nuclei", "dalfox", "jwt_tool", "sqlmap")
            assert isinstance(tool.timeout, int)
            assert isinstance(tool.args_template, list)
            assert "{target}" in " ".join(tool.args_template) or "url" in tool.args_template

    def test_hypothesis_with_none_values(self, empty_plan):
        """Hypothesis with None values should not crash."""
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            update_plan_from_hypotheses,
        )
        hyp = {
            "suggested_tools": None,
            "confidence": None,
            "root_cause_key": None,
            "description": None,
        }
        # Should not crash
        update_plan_from_hypotheses(empty_plan, [hyp])
        assert empty_plan.activated_phases == 0

    def test_hypothesis_with_zero_confidence_threshold_boundary(self, empty_plan):
        """Confidence exactly 0.5 should activate (>= 0.5)."""
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            update_plan_from_hypotheses,
        )
        hyp = {
            "suggested_tools": ["sqlmap"],
            "confidence": 0.5,
            "root_cause_key": "boundary_test",
            "description": "At threshold",
        }
        update_plan_from_hypotheses(empty_plan, [hyp])
        assert empty_plan.activated_phases == 1
        assert empty_plan.total_phases == 1


# =========================================================================
# Integration with WorkflowPlan
# =========================================================================


class TestWorkflowPlanIntegration:
    """Test that hypothesis phases integrate correctly with WorkflowPlan methods."""

    def test_get_plan_summary_includes_hypothesis_phases(
        self, empty_plan, sql_injection_hypothesis, ssrf_hypothesis
    ):
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            update_plan_from_hypotheses,
        )
        update_plan_from_hypotheses(empty_plan, [sql_injection_hypothesis, ssrf_hypothesis])

        summary = empty_plan.get_plan_summary() if hasattr(empty_plan, "get_plan_summary") else {}
        if summary:
            assert "input_validation" in str(summary.get("phases", []))
            assert "ssrf_testing" in str(summary.get("phases", []))

    def test_get_coverage_report_after_hypothesis_activation(
        self, populated_plan, sql_injection_hypothesis, ssrf_hypothesis
    ):
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            update_plan_from_hypotheses,
        )
        update_plan_from_hypotheses(populated_plan, [sql_injection_hypothesis, ssrf_hypothesis])

        report = populated_plan.get_coverage_report()
        assert report["activated_count"] == 4  # 2 existing + 2 new
        assert report["total_phases"] == 4
        assert report["coverage_pct"] == 1.0
        assert "input_validation" in report["activated"]
        assert "ssrf_testing" in report["activated"]
        assert "auth_testing" in report["activated"]
        assert "api_scan" in report["activated"]

    def test_skipped_phases_preserved_when_hypotheses_added(self, populated_plan):
        """Skipped phases list should not be affected by hypothesis activation."""
        from orchestrator_pkg.planning.hypothesis_planning_bridge import (
            update_plan_from_hypotheses,
        )
        populated_plan.skipped_phases = [
            {"name": "tech_deep_scan", "reason": "no tech_stack detected"},
        ]
        hyp = {
            "suggested_tools": ["sqlmap"],
            "confidence": 0.8,
            "root_cause_key": "cwe:89",
            "description": "SQLi",
        }
        update_plan_from_hypotheses(populated_plan, [hyp])

        assert len(populated_plan.skipped_phases) == 1
        assert populated_plan.skipped_phases[0]["name"] == "tech_deep_scan"
        assert populated_plan.activated_phases == 3  # 2 existing + 1 new
