"""Tests for TestGraphQLIntrospection from adaptive_planner."""


from orchestrator_pkg.planning.adaptive_planner import (
    AdaptiveWorkflowPlanner,
)

from .conftest import _make_mock_recon


class TestGraphQLIntrospection:
    """Test the graphql_introspection phase activation and tool generation."""

    def test_has_graphql_flag_activates_gql_testing(self):
        """has_graphql=True on ReconContext activates graphql_introspection."""
        rc = _make_mock_recon(has_graphql=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "graphql_introspection" for p in plan.phases), (
            f"Expected graphql_introspection in phases: {[p.name for p in plan.phases]}"
        )

    def test_graphql_endpoints_list_activates_gql_testing(self):
        """graphql_endpoints list on ReconContext activates graphql_introspection."""
        rc = _make_mock_recon(graphql_endpoints=["/graphql", "/graphql/v1"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "graphql_introspection" for p in plan.phases)

    def test_graphql_tech_keyword_activates_gql_testing(self):
        """GraphQL keywords in tech_stack activate graphql_introspection."""
        rc = _make_mock_recon(tech_stack=["Node.js", "Apollo", "GraphQL"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "graphql_introspection" for p in plan.phases)

    def test_hasura_tech_keyword_activates_gql_testing(self):
        """Hasura keyword in tech_stack activates graphql_introspection."""
        rc = _make_mock_recon(tech_stack=["Hasura", "PostgreSQL"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "graphql_introspection" for p in plan.phases)

    def test_gql_abbreviation_activates_gql_testing(self):
        """gql abbreviation in tech_stack activates graphql_introspection."""
        rc = _make_mock_recon(tech_stack=["gql", "express"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "graphql_introspection" for p in plan.phases)

    def test_api_endpoint_activates_gql_testing(self):
        """API endpoints trigger graphql_introspection (GraphQL is an API technology)."""
        rc = _make_mock_recon(has_api=True, api_endpoints=["/api/v1/users"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "graphql_introspection" for p in plan.phases)

    def test_no_graphql_signals_no_activation(self):
        """No GraphQL signals does NOT activate graphql_introspection."""
        rc = _make_mock_recon(tech_stack=["WordPress"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert not any(p.name == "graphql_introspection" for p in plan.phases)

    def test_gql_testing_has_tools(self):
        """Activated graphql_introspection phase has tool tasks."""
        rc = _make_mock_recon(has_graphql=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        gql_phase = next(p for p in plan.phases if p.name == "graphql_introspection")
        assert len(gql_phase.tools) >= 2, (
            f"Expected 2+ GraphQL testing tools, got {len(gql_phase.tools)}"
        )

    def test_api_scan_triggers_gql_testing(self):
        """api_scan has graphql_introspection in its triggers."""
        rc = _make_mock_recon(has_api=True, api_endpoints=["/api/v1"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        api_phase = next(p for p in plan.phases if p.name == "api_scan")
        assert "graphql_introspection" in api_phase.triggers

    def test_gql_triggers_include_access_control(self):
        """graphql_introspection triggers include access_control."""
        rc = _make_mock_recon(has_graphql=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        gql_phase = next(p for p in plan.phases if p.name == "graphql_introspection")
        assert "access_control" in gql_phase.triggers
        assert "input_validation" in gql_phase.triggers


# ── WebSocket Testing Tests ────────────────────────────────────────────────
