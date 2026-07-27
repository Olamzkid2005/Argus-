"""Tests for TestCorsOriginTesting from adaptive_planner."""

from types import SimpleNamespace

from orchestrator_pkg.planning.adaptive_planner import (
    AdaptiveWorkflowPlanner,
    TestingPhase,
    ToolTask,
    WorkflowPlan,
)

from .conftest import _make_mock_recon


class TestCorsOriginTesting:
    """Test the cors_origin_testing phase activation and tool generation."""

    def test_has_cors_flag_activates_cors_testing(self):
        """has_cors=True on ReconContext activates cors_origin_testing."""
        rc = _make_mock_recon(has_cors=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "cors_origin_testing" for p in plan.phases), (
            f"Expected cors_origin_testing in phases: {[p.name for p in plan.phases]}"
        )

    def test_cors_headers_list_activates_cors_testing(self):
        """cors_headers list on ReconContext activates cors_origin_testing."""
        rc = _make_mock_recon(cors_headers=["Access-Control-Allow-Origin: *"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "cors_origin_testing" for p in plan.phases)

    def test_api_endpoint_activates_cors_testing(self):
        """API endpoints trigger cors_origin_testing (CORS is an API concern)."""
        rc = _make_mock_recon(has_api=True, api_endpoints=["/api/v1/users"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "cors_origin_testing" for p in plan.phases)

    def test_cors_tech_keyword_activates_cors_testing(self):
        """CORS keywords in tech_stack activate cors_origin_testing."""
        rc = _make_mock_recon(tech_stack=["React", "REST", "CORS headers"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "cors_origin_testing" for p in plan.phases)

    def test_no_cors_signals_no_activation(self):
        """No CORS signals does NOT activate cors_origin_testing."""
        rc = _make_mock_recon(tech_stack=["WordPress"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert not any(p.name == "cors_origin_testing" for p in plan.phases)

    def test_cors_testing_has_tools(self):
        """Activated cors_origin_testing phase has tool tasks."""
        rc = _make_mock_recon(has_api=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        cors_phase = next(p for p in plan.phases if p.name == "cors_origin_testing")
        assert len(cors_phase.tools) >= 2, (
            f"Expected 2+ CORS testing tools, got {len(cors_phase.tools)}"
        )

    def test_cors_testing_depends_on_api(self):
        """cors_origin_testing depends_on api_scan, so api_scan comes first."""
        rc = _make_mock_recon(has_api=True, api_endpoints=["/api/v1"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        names = [p.name for p in plan.phases]
        assert "api_scan" in names
        assert "cors_origin_testing" in names
        assert names.index("api_scan") < names.index("cors_origin_testing"), (
            f"api_scan should come before cors_origin_testing: {names}"
        )

    def test_api_scan_triggers_cors(self):
        """api_scan has cors_origin_testing in its triggers."""
        rc = _make_mock_recon(has_api=True, api_endpoints=["/api/v1"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        api_phase = next(p for p in plan.phases if p.name == "api_scan")
        assert "cors_origin_testing" in api_phase.triggers


# ── Rate Limit Testing Tests ──────────────────────────────────────────────
