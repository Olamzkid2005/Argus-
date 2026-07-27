"""Tests for TestNoSqlInjection from adaptive_planner."""

from types import SimpleNamespace

from orchestrator_pkg.planning.adaptive_planner import (
    AdaptiveWorkflowPlanner,
    TestingPhase,
    ToolTask,
    WorkflowPlan,
)

from .conftest import _make_mock_recon


class TestNoSqlInjection:
    """Test the no_sql_injection phase activation and tool generation."""

    def test_has_nosql_flag_activates(self):
        """has_nosql=True on ReconContext activates no_sql_injection."""
        rc = _make_mock_recon(has_nosql=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "no_sql_injection" for p in plan.phases), (
            f"Expected no_sql_injection in phases: {[p.name for p in plan.phases]}"
        )

    def test_nosql_endpoints_list_activates(self):
        """nosql_endpoints list on ReconContext activates no_sql_injection."""
        rc = _make_mock_recon(nosql_endpoints=["/mongo/query", "/nosql/find"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "no_sql_injection" for p in plan.phases)

    def test_mongodb_tech_activates(self):
        """MongoDB in tech_stack activates no_sql_injection."""
        rc = _make_mock_recon(tech_stack=["MongoDB", "Node.js", "Express"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "no_sql_injection" for p in plan.phases)

    def test_mongoose_tech_activates(self):
        """Mongoose in tech_stack activates no_sql_injection."""
        rc = _make_mock_recon(tech_stack=["Mongoose", "Node.js"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "no_sql_injection" for p in plan.phases)

    def test_firebase_tech_activates(self):
        """Firebase in tech_stack activates no_sql_injection."""
        rc = _make_mock_recon(tech_stack=["Firebase", "Firestore", "React"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "no_sql_injection" for p in plan.phases)

    def test_elasticsearch_tech_activates(self):
        """Elasticsearch in tech_stack activates no_sql_injection."""
        rc = _make_mock_recon(tech_stack=["Elasticsearch", "Kibana", "Python"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "no_sql_injection" for p in plan.phases)

    def test_cassandra_tech_activates(self):
        """Cassandra in tech_stack activates no_sql_injection."""
        rc = _make_mock_recon(tech_stack=["Cassandra", "Java", "Spring"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "no_sql_injection" for p in plan.phases)

    def test_redis_tech_activates(self):
        """Redis in tech_stack activates no_sql_injection."""
        rc = _make_mock_recon(tech_stack=["Redis", "Python", "Flask"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "no_sql_injection" for p in plan.phases)

    def test_dynamodb_tech_activates(self):
        """DynamoDB in tech_stack activates no_sql_injection."""
        rc = _make_mock_recon(tech_stack=["AWS", "DynamoDB", "Lambda"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "no_sql_injection" for p in plan.phases)

    def test_neo4j_tech_activates(self):
        """Neo4j in tech_stack activates no_sql_injection."""
        rc = _make_mock_recon(tech_stack=["Neo4j", "GraphQL", "Node.js"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "no_sql_injection" for p in plan.phases)

    def test_prisma_tech_activates(self):
        """Prisma in tech_stack activates no_sql_injection."""
        rc = _make_mock_recon(tech_stack=["Prisma", "PostgreSQL", "Next.js"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "no_sql_injection" for p in plan.phases)

    def test_api_endpoint_activates_nosql(self):
        """API endpoints activate no_sql_injection (NoSQL queried via API params)."""
        rc = _make_mock_recon(has_api=True, api_endpoints=["/api/v1/users"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "no_sql_injection" for p in plan.phases)

    def test_parameter_urls_activate_nosql(self):
        """Parameter-bearing URLs activate no_sql_injection (injection vector)."""
        rc = _make_mock_recon(parameter_bearing_urls=["/api/data?$where=true"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "no_sql_injection" for p in plan.phases)

    def test_no_nosql_signals_no_activation(self):
        """No NoSQL signals does NOT activate no_sql_injection."""
        rc = _make_mock_recon(target_url="https://example.com")
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert not any(p.name == "no_sql_injection" for p in plan.phases)

    def test_nosql_has_tools(self):
        """Activated no_sql_injection phase has tool tasks."""
        rc = _make_mock_recon(has_nosql=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        nosql_phase = next(p for p in plan.phases if p.name == "no_sql_injection")
        assert len(nosql_phase.tools) >= 2, (
            f"Expected 2+ NoSQL testing tools, got {len(nosql_phase.tools)}"
        )

    def test_nosql_depends_on_input_validation(self):
        """no_sql_injection depends_on input_validation, so input_validation comes first."""
        rc = _make_mock_recon(
            has_nosql=True,
            parameter_bearing_urls=["/api/data?$where=true"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        names = [p.name for p in plan.phases]
        assert "input_validation" in names
        assert "no_sql_injection" in names
        assert names.index("input_validation") < names.index("no_sql_injection"), (
            f"input_validation should come before no_sql_injection: {names}"
        )

    def test_input_validation_triggers_nosql(self):
        """input_validation has no_sql_injection in its triggers."""
        rc = _make_mock_recon(
            has_nosql=True,
            parameter_bearing_urls=["/api/data?$where=true"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        iv_phase = next(p for p in plan.phases if p.name == "input_validation")
        assert "no_sql_injection" in iv_phase.triggers

    def test_nosql_triggers_access_control(self):
        """no_sql_injection triggers include access_control."""
        rc = _make_mock_recon(has_nosql=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        nosql_phase = next(p for p in plan.phases if p.name == "no_sql_injection")
        assert "access_control" in nosql_phase.triggers


# ── LDAP Injection Testing Tests ─────────────────────────────────────────
