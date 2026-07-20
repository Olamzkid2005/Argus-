"""Tests for orchestrator_pkg.planning.adaptive_planner — Category: class"""

from types import SimpleNamespace

from orchestrator_pkg.planning.adaptive_planner import (
    AdaptiveWorkflowPlanner,
    ToolTask,
    TestingPhase,
    WorkflowPlan,
)


def _make_mock_recon(**overrides) -> SimpleNamespace:
    """Create a minimal ReconContext-like SimpleNamespace with specified attributes.

    Using SimpleNamespace instead of MagicMock ensures ``hasattr()`` returns
    ``False`` for unset attributes, which matches how the activation functions
    use ``hasattr`` guards in the planner.
    """
    defaults = {
        "target_url": "https://example.com",
        "live_endpoints": ["https://example.com"],
        "subdomains": [],
        "open_ports": [],
        "tech_stack": [],
        "crawled_paths": [],
        "parameter_bearing_urls": [],
        "auth_endpoints": [],
        "api_endpoints": [],
        "findings_count": 0,
        "has_login_page": False,
        "has_api": False,
        "has_file_upload": False,
    }
    merged = {**defaults, **overrides}
    return SimpleNamespace(**merged)


# ── Activation Tests ───────────────────────────────────────────────────


class TestActivationRules:
    """Test that phases activate correctly based on ReconContext signals."""

    def test_empty_recon_returns_empty_plan(self):
        """No recon context yields an empty plan."""
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(None)
        assert len(plan.phases) == 0
        assert plan.activated_phases == 0

    def test_bare_minimum_recon_no_phases(self):
        """A target with no signals activates no phases."""
        rc = _make_mock_recon(target_url="https://example.com")
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert len(plan.phases) == 0
        assert plan.activated_phases == 0

    def test_login_page_activates_auth_phase(self):
        """has_login_page=True activates auth_testing."""
        rc = _make_mock_recon(has_login_page=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "auth_testing" for p in plan.phases), (
            f"Expected auth_testing in phases: {[p.name for p in plan.phases]}"
        )

    def test_auth_endpoints_activates_auth_phase(self):
        """Auth endpoints trigger auth_testing."""
        rc = _make_mock_recon(auth_endpoints=["/login", "/oauth/callback"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "auth_testing" for p in plan.phases)

    def test_api_endpoints_activate_api_phase(self):
        """API endpoints trigger api_scan."""
        rc = _make_mock_recon(has_api=True, api_endpoints=["/api/v1/users", "/api/v1/data"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "api_scan" for p in plan.phases)

    def test_parameter_urls_activate_input_validation(self):
        """Parameter-bearing URLs trigger input_validation."""
        rc = _make_mock_recon(parameter_bearing_urls=["/page?q=test"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "input_validation" for p in plan.phases)

    def test_file_upload_flag(self):
        """has_file_upload=True triggers file_upload_scan."""
        rc = _make_mock_recon(has_file_upload=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "file_upload_scan" for p in plan.phases)

    def test_open_ports_activate_infrastructure(self):
        """Open ports trigger infrastructure_scan."""
        rc = _make_mock_recon(
            open_ports=[{"port": 80, "service": "http"}, {"port": 3306, "service": "mysql"}]
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "infrastructure_scan" for p in plan.phases)

    def test_tech_stack_activates_tech_scan(self):
        """Recognized tech stack triggers tech_deep_scan."""
        rc = _make_mock_recon(tech_stack=["WordPress", "PHP", "MySQL"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "tech_deep_scan" for p in plan.phases)

    def test_unrecognized_tech_no_activation(self):
        """Unrecognized tech stack does not trigger tech_deep_scan."""
        rc = _make_mock_recon(tech_stack=["RareFramework", "CustomServer"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert not any(p.name == "tech_deep_scan" for p in plan.phases)

    def test_full_engagement_signal(self):
        """A realistic target with multiple signals activates appropriate phases."""
        rc = _make_mock_recon(
            target_url="https://example.com",
            tech_stack=["WordPress", "PHP", "nginx"],
            has_login_page=True,
            auth_endpoints=["/wp-login.php"],
            parameter_bearing_urls=["/page?id=1"],
            open_ports=[{"port": 80, "service": "http"}, {"port": 443, "service": "https"}],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        activated = {p.name for p in plan.phases}
        # Auth and tech should activate
        assert "auth_testing" in activated
        assert "tech_deep_scan" in activated
        # No API signal -> api_scan should not activate
        assert "api_scan" not in activated
        assert plan.activated_phases > 0
        assert len(plan.skipped_phases) > 0


# ── Ordering Tests ─────────────────────────────────────────────────────


class TestPhaseOrdering:
    """Test that phases are ordered correctly with dependency resolution."""

    def test_dependencies_ordered_first(self):
        """Dependencies appear before dependents."""
        rc = _make_mock_recon(
            has_login_page=True,
            auth_endpoints=["/login"],
            has_api=True,
            api_endpoints=["/api/v1"],
            tech_stack=["WordPress"],
            parameter_bearing_urls=["/page?q=1"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        names = [p.name for p in plan.phases]
        # tech_deep_scan has order 10, should come before auth_testing (order 20)
        assert names.index("tech_deep_scan") < names.index("auth_testing"), (
            f"tech_deep_scan should come before auth_testing: {names}"
        )
        # auth_testing should come before access_control (depends_on auth_testing)
        assert names.index("auth_testing") < names.index("access_control"), (
            f"auth_testing should come before access_control: {names}"
        )

    def test_phase_has_tools_when_activated(self):
        """Activated phases have tool tasks generated."""
        rc = _make_mock_recon(
            has_login_page=True,
            tech_stack=["WordPress"],
            parameter_bearing_urls=["/page?id=1"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        for phase in plan.phases:
            assert len(phase.tools) > 0, (
                f"Phase '{phase.name}' has no tools"
            )
            for task in phase.tools:
                assert isinstance(task, ToolTask)
                assert task.tool_name


# ── Tool Args Resolution Tests ─────────────────────────────────────────


class TestToolArgsResolution:
    """Test that tool argument templates are resolved correctly."""

    def test_basic_resolution(self):
        """Placeholder strings are replaced with actual values."""
        task = ToolTask(
            tool_name="nuclei",
            description="test",
            args_template=["-u", "{target}", "-jsonl", "-silent"],
        )
        resolved = AdaptiveWorkflowPlanner.resolve_tool_args(task, "https://example.com", "eng-123")
        assert resolved == ["-u", "https://example.com", "-jsonl", "-silent"]

    def test_multiple_placeholders(self):
        """Multiple different placeholders are resolved."""
        task = ToolTask(
            tool_name="test_tool",
            args_template=["{target}", "{engagement_id}", "{targets}"],
        )
        resolved = AdaptiveWorkflowPlanner.resolve_tool_args(task, "https://target.com", "eng-001")
        assert resolved == ["https://target.com", "eng-001", "https://target.com"]

    def test_no_placeholders(self):
        """Args without placeholders pass through unchanged."""
        task = ToolTask(tool_name="test_tool", args_template=["--batch", "--json"])
        resolved = AdaptiveWorkflowPlanner.resolve_tool_args(task, "https://x.com", "eng-1")
        assert resolved == ["--batch", "--json"]


# ── Formatting Tests ───────────────────────────────────────────────────


class TestFormatting:
    """Test plan formatting and summary methods."""

    def test_format_plan_for_agent(self):
        """format_plan_for_agent returns a non-empty string with plan details."""
        rc = _make_mock_recon(
            has_login_page=True,
            tech_stack=["WordPress"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        formatted = planner.format_plan_for_agent(plan)
        assert "=== ADAPTIVE TESTING PLAN ===" in formatted
        assert "=== END TESTING PLAN ===" in formatted
        assert "Phase 1:" in formatted
        assert "nuclei" in formatted.lower()

    def test_format_empty_plan(self):
        """Empty plans produce empty format output."""
        planner = AdaptiveWorkflowPlanner()
        formatted = planner.format_plan_for_agent(WorkflowPlan())
        assert formatted == ""

    def test_get_plan_summary(self):
        """get_plan_summary returns a serializable dict."""
        rc = _make_mock_recon(has_login_page=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        summary = planner.get_plan_summary(plan)
        assert isinstance(summary, dict)
        assert "phases" in summary
        assert "activated_phases" in summary
        assert "skipped" in summary


# ── Dynamic Phase Chaining Tests ───────────────────────────────────────


class TestDynamicChaining:
    """Test that findings from completed phases trigger follow-up phases."""

    def test_no_findings_no_trigger(self):
        """No findings means no trigger phases are added."""
        planner = AdaptiveWorkflowPlanner()
        phase = TestingPhase(
            name="auth_testing",
            order=20,
            triggers=["session_analysis"],
        )
        plan = WorkflowPlan(phases=[phase])
        updated = planner.update_plan_from_results(plan, "auth_testing", [])
        assert len(updated.phases) == 1  # Only auth_testing remains

    def test_unknown_phase_no_trigger(self):
        """Completing an unknown phase does not trigger anything."""
        planner = AdaptiveWorkflowPlanner()
        plan = WorkflowPlan(phases=[])
        updated = planner.update_plan_from_results(
            plan, "nonexistent", [{"type": "FAKE"}]
        )
        assert len(updated.phases) == 0

    def test_no_triggers_no_change(self):
        """A phase without triggers does not activate anything new."""
        planner = AdaptiveWorkflowPlanner()
        phase = TestingPhase(name="infrastructure_scan", order=70, triggers=[])
        plan = WorkflowPlan(phases=[phase])
        updated = planner.update_plan_from_results(
            plan, "infrastructure_scan", [{"type": "OPEN_PORT"}]
        )
        assert len(updated.phases) == 1


# ── GraphQL Introspection Tests ─────────────────────────────────────────────


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


class TestWebSocketTesting:
    """Test the websocket_testing phase activation and tool generation."""

    def test_has_websocket_flag_activates_ws_testing(self):
        """has_websocket=True on ReconContext activates websocket_testing."""
        rc = _make_mock_recon(has_websocket=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "websocket_testing" for p in plan.phases), (
            f"Expected websocket_testing in phases: {[p.name for p in plan.phases]}"
        )

    def test_websocket_endpoints_list_activates_ws_testing(self):
        """websocket_endpoints list on ReconContext activates websocket_testing."""
        rc = _make_mock_recon(websocket_endpoints=["wss://example.com/ws"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "websocket_testing" for p in plan.phases)

    def test_websocket_tech_keyword_activates_ws_testing(self):
        """WebSocket keywords in tech_stack activate websocket_testing."""
        rc = _make_mock_recon(tech_stack=["Node.js", "Socket.IO", "Redis"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "websocket_testing" for p in plan.phases)

    def test_socketio_abbreviation_activates_ws_testing(self):
        """socket.io abbreviation in tech_stack activates websocket_testing."""
        rc = _make_mock_recon(tech_stack=["socket.io", "express"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "websocket_testing" for p in plan.phases)

    def test_api_endpoint_activates_ws_testing(self):
        """API endpoints trigger websocket_testing (WS often accompanies APIs)."""
        rc = _make_mock_recon(has_api=True, api_endpoints=["/api/v1/users"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "websocket_testing" for p in plan.phases)

    def test_no_websocket_signals_no_activation(self):
        """No WebSocket signals does NOT activate websocket_testing."""
        rc = _make_mock_recon(tech_stack=["WordPress"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert not any(p.name == "websocket_testing" for p in plan.phases)

    def test_ws_testing_has_tools(self):
        """Activated websocket_testing phase has tool tasks."""
        rc = _make_mock_recon(has_websocket=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        ws_phase = next(p for p in plan.phases if p.name == "websocket_testing")
        assert len(ws_phase.tools) >= 2, (
            f"Expected 2+ WebSocket testing tools, got {len(ws_phase.tools)}"
        )

    def test_ws_testing_depends_on_api(self):
        """websocket_testing depends_on api_scan, so api_scan comes first."""
        rc = _make_mock_recon(has_api=True, api_endpoints=["/api/v1"], has_websocket=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        names = [p.name for p in plan.phases]
        assert "api_scan" in names
        assert "websocket_testing" in names
        assert names.index("api_scan") < names.index("websocket_testing"), (
            f"api_scan should come before websocket_testing: {names}"
        )

    def test_api_scan_triggers_ws_testing(self):
        """api_scan has websocket_testing in its triggers."""
        rc = _make_mock_recon(has_api=True, api_endpoints=["/api/v1"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        api_phase = next(p for p in plan.phases if p.name == "api_scan")
        assert "websocket_testing" in api_phase.triggers

    def test_ws_testing_triggers_include_access_control(self):
        """websocket_testing triggers include access_control."""
        rc = _make_mock_recon(has_websocket=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        ws_phase = next(p for p in plan.phases if p.name == "websocket_testing")
        assert "access_control" in ws_phase.triggers
        assert "input_validation" in ws_phase.triggers


# ── CORS Origin Testing Tests ─────────────────────────────────────────────


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


class TestRateLimitTesting:
    """Test the rate_limit_testing phase activation and tool generation."""

    def test_login_page_activates_rate_limit(self):
        """has_login_page=True activates rate_limit_testing."""
        rc = _make_mock_recon(has_login_page=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "rate_limit_testing" for p in plan.phases), (
            f"Expected rate_limit_testing in phases: {[p.name for p in plan.phases]}"
        )

    def test_auth_endpoints_activate_rate_limit(self):
        """Auth endpoints trigger rate_limit_testing."""
        rc = _make_mock_recon(auth_endpoints=["/login", "/reset-password"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "rate_limit_testing" for p in plan.phases)

    def test_api_endpoints_activate_rate_limit(self):
        """API endpoints trigger rate_limit_testing."""
        rc = _make_mock_recon(has_api=True, api_endpoints=["/api/v1/data"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "rate_limit_testing" for p in plan.phases)

    def test_no_rate_limit_targets_no_activation(self):
        """No auth/API endpoints does NOT activate rate_limit_testing."""
        rc = _make_mock_recon(target_url="https://example.com")
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert not any(p.name == "rate_limit_testing" for p in plan.phases)

    def test_rate_limit_has_tools(self):
        """Activated rate_limit_testing phase has tool tasks."""
        rc = _make_mock_recon(has_login_page=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        rl_phase = next(p for p in plan.phases if p.name == "rate_limit_testing")
        assert len(rl_phase.tools) >= 2, (
            f"Expected 2+ rate limit testing tools, got {len(rl_phase.tools)}"
        )

    def test_rate_limit_ordered_after_auth(self):
        """rate_limit_testing depends_on auth_testing, so auth comes first."""
        rc = _make_mock_recon(has_login_page=True, auth_endpoints=["/login"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        names = [p.name for p in plan.phases]
        assert "auth_testing" in names
        assert "rate_limit_testing" in names
        assert names.index("auth_testing") < names.index("rate_limit_testing"), (
            f"auth_testing should come before rate_limit_testing: {names}"
        )

    def test_full_engagement_activates_rate_limit(self):
        """A realistic target with auth activates rate_limit_testing alongside others."""
        rc = _make_mock_recon(
            target_url="https://example.com",
            has_login_page=True,
            auth_endpoints=["/login"],
            tech_stack=["WordPress"],
            parameter_bearing_urls=["/page?id=1"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        activated = {p.name for p in plan.phases}
        assert "rate_limit_testing" in activated
        assert "auth_testing" in activated


# ── Template Injection (SSTI) Tests ─────────────────────────────────────────


class TestTemplateInjection:
    """Test the template_injection phase activation and tool generation."""

    def test_has_template_injection_flag_activates(self):
        """has_template_injection=True activates template_injection."""
        rc = _make_mock_recon(has_template_injection=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "template_injection" for p in plan.phases), (
            f"Expected template_injection in phases: {[p.name for p in plan.phases]}"
        )

    def test_template_engines_list_activates(self):
        """template_engines list on ReconContext activates template_injection."""
        rc = _make_mock_recon(template_engines=["Jinja2", "Twig"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "template_injection" for p in plan.phases)

    def test_jinja_tech_activates_ssti(self):
        """Jinja/Jinja2 in tech_stack activates template_injection."""
        rc = _make_mock_recon(tech_stack=["Flask", "Jinja2", "Python"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "template_injection" for p in plan.phases)

    def test_twig_tech_activates_ssti(self):
        """Twig in tech_stack activates template_injection."""
        rc = _make_mock_recon(tech_stack=["Symfony", "Twig", "PHP"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "template_injection" for p in plan.phases)

    def test_blade_tech_activates_ssti(self):
        """Blade in tech_stack activates template_injection."""
        rc = _make_mock_recon(tech_stack=["Laravel", "Blade", "PHP"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "template_injection" for p in plan.phases)

    def test_pug_tech_activates_ssti(self):
        """Pug in tech_stack activates template_injection."""
        rc = _make_mock_recon(tech_stack=["Express", "Pug", "Node.js"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "template_injection" for p in plan.phases)

    def test_velocity_tech_activates_ssti(self):
        """Velocity in tech_stack activates template_injection."""
        rc = _make_mock_recon(tech_stack=["Spring", "Velocity", "Java"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "template_injection" for p in plan.phases)

    def test_parameter_urls_activate_ssti(self):
        """Parameter-bearing URLs activate template_injection (SSTI vector)."""
        rc = _make_mock_recon(parameter_bearing_urls=["/page?name=test"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "template_injection" for p in plan.phases)

    def test_no_ssti_signals_no_activation(self):
        """No template signals does NOT activate template_injection."""
        rc = _make_mock_recon(target_url="https://example.com")
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert not any(p.name == "template_injection" for p in plan.phases)

    def test_ssti_has_tools(self):
        """Activated template_injection phase has tool tasks."""
        rc = _make_mock_recon(tech_stack=["Flask", "Jinja2"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        ssti_phase = next(p for p in plan.phases if p.name == "template_injection")
        assert len(ssti_phase.tools) >= 2, (
            f"Expected 2+ SSTI testing tools, got {len(ssti_phase.tools)}"
        )

    def test_ssti_depends_on_input_validation(self):
        """template_injection depends_on input_validation, so input_validation comes first."""
        rc = _make_mock_recon(
            parameter_bearing_urls=["/page?name=test"],
            tech_stack=["Flask", "Jinja2"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        names = [p.name for p in plan.phases]
        assert "input_validation" in names
        assert "template_injection" in names
        assert names.index("input_validation") < names.index("template_injection"), (
            f"input_validation should come before template_injection: {names}"
        )

    def test_input_validation_triggers_ssti(self):
        """input_validation has template_injection in its triggers."""
        rc = _make_mock_recon(parameter_bearing_urls=["/page?id=1"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        iv_phase = next(p for p in plan.phases if p.name == "input_validation")
        assert "template_injection" in iv_phase.triggers

    def test_ssti_triggers_access_control(self):
        """template_injection triggers include access_control."""
        rc = _make_mock_recon(tech_stack=["Flask", "Jinja2"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        ssti_phase = next(p for p in plan.phases if p.name == "template_injection")
        assert "access_control" in ssti_phase.triggers


# ── Deserialization Testing Tests ───────────────────────────────────────────


class TestDeserializationTesting:
    """Test the deserialization_testing phase activation and tool generation."""

    def test_has_deserialization_flag_activates(self):
        """has_deserialization=True activates deserialization_testing."""
        rc = _make_mock_recon(has_deserialization=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "deserialization_testing" for p in plan.phases), (
            f"Expected deserialization_testing in phases: {[p.name for p in plan.phases]}"
        )

    def test_deserialization_libs_list_activates(self):
        """deserialization_libs list activates deserialization_testing."""
        rc = _make_mock_recon(deserialization_libs=["pickle", "PyYAML"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "deserialization_testing" for p in plan.phases)

    def test_pickle_tech_activates_deser(self):
        """Pickle in tech_stack activates deserialization_testing."""
        rc = _make_mock_recon(tech_stack=["Python", "pickle", "Flask"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "deserialization_testing" for p in plan.phases)

    def test_jackson_tech_activates_deser(self):
        """Jackson in tech_stack activates deserialization_testing."""
        rc = _make_mock_recon(tech_stack=["Spring", "Jackson", "Java"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "deserialization_testing" for p in plan.phases)

    def test_xstream_tech_activates_deser(self):
        """XStream in tech_stack activates deserialization_testing."""
        rc = _make_mock_recon(tech_stack=["Java", "XStream"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "deserialization_testing" for p in plan.phases)

    def test_fastjson_tech_activates_deser(self):
        """Fastjson in tech_stack activates deserialization_testing."""
        rc = _make_mock_recon(tech_stack=["Java", "Fastjson", "Spring Boot"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "deserialization_testing" for p in plan.phases)

    def test_api_endpoint_activates_deser(self):
        """API endpoints trigger deserialization_testing (deserialization is common via APIs)."""
        rc = _make_mock_recon(has_api=True, api_endpoints=["/api/v1/data"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "deserialization_testing" for p in plan.phases)

    def test_parameter_urls_activate_deser(self):
        """Parameter-bearing URLs activate deserialization_testing."""
        rc = _make_mock_recon(parameter_bearing_urls=["/api/data?payload=test"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "deserialization_testing" for p in plan.phases)

    def test_no_deser_signals_no_activation(self):
        """No deserialization signals does NOT activate deserialization_testing."""
        rc = _make_mock_recon(target_url="https://example.com")
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert not any(p.name == "deserialization_testing" for p in plan.phases)

    def test_deser_has_tools(self):
        """Activated deserialization_testing phase has tool tasks."""
        rc = _make_mock_recon(tech_stack=["Java", "Jackson"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        deser_phase = next(p for p in plan.phases if p.name == "deserialization_testing")
        assert len(deser_phase.tools) >= 2, (
            f"Expected 2+ deserialization testing tools, got {len(deser_phase.tools)}"
        )

    def test_deser_depends_on_input_validation(self):
        """deserialization_testing depends_on input_validation, which comes first."""
        rc = _make_mock_recon(
            parameter_bearing_urls=["/api/data?payload=test"],
            has_api=True,
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        names = [p.name for p in plan.phases]
        assert "input_validation" in names
        assert "deserialization_testing" in names
        assert names.index("input_validation") < names.index("deserialization_testing"), (
            f"input_validation should come before deserialization_testing: {names}"
        )

    def test_deser_triggers_access_control(self):
        """deserialization_testing triggers include access_control."""
        rc = _make_mock_recon(tech_stack=["Java", "Jackson"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        deser_phase = next(p for p in plan.phases if p.name == "deserialization_testing")
        assert "access_control" in deser_phase.triggers

    def test_deser_triggers_cloud_metadata(self):
        """deserialization_testing triggers include cloud_metadata_probe."""
        rc = _make_mock_recon(tech_stack=["Java", "Jackson"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        deser_phase = next(p for p in plan.phases if p.name == "deserialization_testing")
        assert "cloud_metadata_probe" in deser_phase.triggers


# ── SSRF Testing Tests ─────────────────────────────────────────────────────


class TestSsrfTesting:
    """Test the ssrf_testing phase activation and tool generation."""

    def test_has_ssrf_flag_activates_ssrf_testing(self):
        """has_ssrf=True on ReconContext activates ssrf_testing."""
        rc = _make_mock_recon(has_ssrf=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "ssrf_testing" for p in plan.phases), (
            f"Expected ssrf_testing in phases: {[p.name for p in plan.phases]}"
        )

    def test_ssrf_signals_list_activates_ssrf_testing(self):
        """ssrf_signals list on ReconContext activates ssrf_testing."""
        rc = _make_mock_recon(ssrf_signals=["parameter_url=http://internal/"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "ssrf_testing" for p in plan.phases)

    def test_parameter_urls_activate_ssrf_testing(self):
        """Parameter-bearing URLs activate ssrf_testing (SSRF vector)."""
        rc = _make_mock_recon(parameter_bearing_urls=["/page?url=http://example.com"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "ssrf_testing" for p in plan.phases)

    def test_file_upload_activates_ssrf_testing(self):
        """File upload presence activates ssrf_testing (URL-based file sources)."""
        rc = _make_mock_recon(has_file_upload=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "ssrf_testing" for p in plan.phases)

    def test_ssrf_tech_keyword_activates_ssrf_testing(self):
        """SSRF-related keywords in tech_stack activate ssrf_testing."""
        rc = _make_mock_recon(tech_stack=["PHP", "cURL", "allow_url_fopen"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "ssrf_testing" for p in plan.phases)

    def test_guzzle_tech_keyword_activates_ssrf_testing(self):
        """Guzzle HTTP client in tech_stack activates ssrf_testing."""
        rc = _make_mock_recon(tech_stack=["Laravel", "Guzzle", "PHP"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "ssrf_testing" for p in plan.phases)

    def test_no_ssrf_signals_no_activation(self):
        """No SSRF signals does NOT activate ssrf_testing."""
        rc = _make_mock_recon(target_url="https://example.com")
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert not any(p.name == "ssrf_testing" for p in plan.phases)

    def test_ssrf_testing_has_tools(self):
        """Activated ssrf_testing phase has tool tasks."""
        rc = _make_mock_recon(has_ssrf=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        ssrf_phase = next(p for p in plan.phases if p.name == "ssrf_testing")
        assert len(ssrf_phase.tools) >= 2, (
            f"Expected 2+ SSRF testing tools, got {len(ssrf_phase.tools)}"
        )

    def test_ssrf_testing_depends_on_input_validation(self):
        """ssrf_testing depends_on input_validation, so input_validation comes first."""
        rc = _make_mock_recon(
            parameter_bearing_urls=["/page?url=http://example.com"],
            has_ssrf=True,
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        names = [p.name for p in plan.phases]
        assert "input_validation" in names
        assert "ssrf_testing" in names
        assert names.index("input_validation") < names.index("ssrf_testing"), (
            f"input_validation should come before ssrf_testing: {names}"
        )

    def test_input_validation_triggers_ssrf(self):
        """input_validation has ssrf_testing in its triggers."""
        rc = _make_mock_recon(parameter_bearing_urls=["/page?id=1"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        iv_phase = next(p for p in plan.phases if p.name == "input_validation")
        assert "ssrf_testing" in iv_phase.triggers

    def test_ssrf_triggers_cloud_metadata(self):
        """ssrf_testing triggers include cloud_metadata_probe."""
        rc = _make_mock_recon(has_ssrf=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        ssrf_phase = next(p for p in plan.phases if p.name == "ssrf_testing")
        assert "cloud_metadata_probe" in ssrf_phase.triggers


# ── Open Redirect Testing Tests ────────────────────────────────────────────


class TestOpenRedirect:
    """Test the open_redirect phase activation and tool generation."""

    def test_has_open_redirect_flag_activates(self):
        """has_open_redirect=True on ReconContext activates open_redirect."""
        rc = _make_mock_recon(has_open_redirect=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "open_redirect" for p in plan.phases), (
            f"Expected open_redirect in phases: {[p.name for p in plan.phases]}"
        )

    def test_redirect_endpoints_list_activates(self):
        """redirect_endpoints list on ReconContext activates open_redirect."""
        rc = _make_mock_recon(redirect_endpoints=["/redirect", "/goto"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "open_redirect" for p in plan.phases)

    def test_param_urls_with_redirect_activates(self):
        """Parameter-bearing URLs with 'redirect' param name activate open_redirect."""
        rc = _make_mock_recon(
            parameter_bearing_urls=["/page?redirect=http://evil.com"]
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "open_redirect" for p in plan.phases)

    def test_param_urls_with_url_param_activates(self):
        """Parameter-bearing URLs with 'url' param name activate open_redirect."""
        rc = _make_mock_recon(
            parameter_bearing_urls=["/page?url=http://evil.com"]
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "open_redirect" for p in plan.phases)

    def test_param_urls_with_next_param_activates(self):
        """Parameter-bearing URLs with 'next' param name activate open_redirect."""
        rc = _make_mock_recon(
            parameter_bearing_urls=["/login?next=/admin"]
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "open_redirect" for p in plan.phases)

    def test_param_urls_with_goto_param_activates(self):
        """Parameter-bearing URLs with 'goto' param name activate open_redirect."""
        rc = _make_mock_recon(
            parameter_bearing_urls=["/page?goto=http://evil.com"]
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "open_redirect" for p in plan.phases)

    def test_param_urls_with_return_param_activates(self):
        """Parameter-bearing URLs with 'return' param name activate open_redirect."""
        rc = _make_mock_recon(
            parameter_bearing_urls=["/checkout?return=/cart"]
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "open_redirect" for p in plan.phases)

    def test_param_urls_with_redirect_uri_activates(self):
        """Parameter-bearing URLs with 'redirect_uri' param name activate open_redirect."""
        rc = _make_mock_recon(
            parameter_bearing_urls=["/oauth/callback?redirect_uri=http://evil.com"]
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "open_redirect" for p in plan.phases)

    def test_redirect_tech_keyword_activates(self):
        """Redirect-related keywords in tech_stack activate open_redirect."""
        rc = _make_mock_recon(tech_stack=["Apache", "mod_rewrite", "PHP"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "open_redirect" for p in plan.phases)

    def test_forward_tech_keyword_activates(self):
        """'forward' keyword in tech_stack activates open_redirect."""
        rc = _make_mock_recon(tech_stack=["Spring Boot", "forward", "Java"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "open_redirect" for p in plan.phases)

    def test_param_urls_without_redirect_no_activation(self):
        """Parameter-bearing URLs without redirect params do NOT activate open_redirect."""
        rc = _make_mock_recon(
            parameter_bearing_urls=["/page?id=1&name=test", "/search?q=hello"]
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert not any(p.name == "open_redirect" for p in plan.phases)

    def test_no_redirect_signals_no_activation(self):
        """No redirect signals does NOT activate open_redirect."""
        rc = _make_mock_recon(target_url="https://example.com")
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert not any(p.name == "open_redirect" for p in plan.phases)

    def test_open_redirect_has_tools(self):
        """Activated open_redirect phase has tool tasks."""
        rc = _make_mock_recon(
            parameter_bearing_urls=["/page?redirect=http://evil.com"]
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        or_phase = next(p for p in plan.phases if p.name == "open_redirect")
        assert len(or_phase.tools) >= 2, (
            f"Expected 2+ open redirect testing tools, got {len(or_phase.tools)}"
        )

    def test_open_redirect_depends_on_input_validation(self):
        """open_redirect depends_on input_validation, so input_validation comes first."""
        rc = _make_mock_recon(
            parameter_bearing_urls=["/page?redirect=http://evil.com", "/page?id=1"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        names = [p.name for p in plan.phases]
        assert "input_validation" in names
        assert "open_redirect" in names
        assert names.index("input_validation") < names.index("open_redirect"), (
            f"input_validation should come before open_redirect: {names}"
        )

    def test_input_validation_triggers_open_redirect(self):
        """input_validation has open_redirect in its triggers."""
        rc = _make_mock_recon(
            parameter_bearing_urls=["/page?redirect=http://evil.com", "/page?id=1"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        iv_phase = next(p for p in plan.phases if p.name == "input_validation")
        assert "open_redirect" in iv_phase.triggers

    def test_open_redirect_triggers_access_control(self):
        """open_redirect triggers include access_control."""
        rc = _make_mock_recon(
            parameter_bearing_urls=["/page?redirect=http://evil.com"]
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        or_phase = next(p for p in plan.phases if p.name == "open_redirect")
        assert "access_control" in or_phase.triggers


# ── XXE (XML External Entity) Testing Tests ────────────────────────────────


class TestXxeTesting:
    """Test the xxe_testing phase activation and tool generation."""

    def test_has_xxe_flag_activates(self):
        """has_xxe=True on ReconContext activates xxe_testing."""
        rc = _make_mock_recon(has_xxe=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "xxe_testing" for p in plan.phases), (
            f"Expected xxe_testing in phases: {[p.name for p in plan.phases]}"
        )

    def test_xml_endpoints_list_activates(self):
        """xml_endpoints list on ReconContext activates xxe_testing."""
        rc = _make_mock_recon(xml_endpoints=["/xml/parse", "/soap/endpoint"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "xxe_testing" for p in plan.phases)

    def test_libxml_tech_activates(self):
        """libxml in tech_stack activates xxe_testing."""
        rc = _make_mock_recon(tech_stack=["PHP", "libxml", "SimpleXML"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "xxe_testing" for p in plan.phases)

    def test_lxml_tech_activates(self):
        """lxml in tech_stack activates xxe_testing."""
        rc = _make_mock_recon(tech_stack=["Python", "lxml", "Flask"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "xxe_testing" for p in plan.phases)

    def test_xerces_tech_activates(self):
        """Xerces in tech_stack activates xxe_testing."""
        rc = _make_mock_recon(tech_stack=["Java", "Xerces", "Spring"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "xxe_testing" for p in plan.phases)

    def test_nokogiri_tech_activates(self):
        """Nokogiri in tech_stack activates xxe_testing."""
        rc = _make_mock_recon(tech_stack=["Ruby", "Nokogiri", "Rails"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "xxe_testing" for p in plan.phases)

    def test_soap_tech_activates(self):
        """SOAP in tech_stack activates xxe_testing."""
        rc = _make_mock_recon(tech_stack=[".NET", "SOAP", "IIS"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "xxe_testing" for p in plan.phases)

    def test_file_upload_activates_xxe(self):
        """File upload presence activates xxe_testing (XML file upload vector)."""
        rc = _make_mock_recon(has_file_upload=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "xxe_testing" for p in plan.phases)

    def test_api_endpoint_activates_xxe(self):
        """API endpoints activate xxe_testing (SOAP/XML APIs)."""
        rc = _make_mock_recon(has_api=True, api_endpoints=["/api/v1/soap"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "xxe_testing" for p in plan.phases)

    def test_parameter_urls_activate_xxe(self):
        """Parameter-bearing URLs activate xxe_testing (XXE injection vector)."""
        rc = _make_mock_recon(parameter_bearing_urls=["/xml/parse?doc=data"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "xxe_testing" for p in plan.phases)

    def test_no_xxe_signals_no_activation(self):
        """No XXE signals does NOT activate xxe_testing."""
        rc = _make_mock_recon(target_url="https://example.com")
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert not any(p.name == "xxe_testing" for p in plan.phases)

    def test_xxe_has_tools(self):
        """Activated xxe_testing phase has tool tasks."""
        rc = _make_mock_recon(has_xxe=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        xxe_phase = next(p for p in plan.phases if p.name == "xxe_testing")
        assert len(xxe_phase.tools) >= 2, (
            f"Expected 2+ XXE testing tools, got {len(xxe_phase.tools)}"
        )

    def test_xxe_depends_on_input_validation(self):
        """xxe_testing depends_on input_validation, so input_validation comes first."""
        rc = _make_mock_recon(
            has_xxe=True,
            parameter_bearing_urls=["/xml/parse?doc=data"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        names = [p.name for p in plan.phases]
        assert "input_validation" in names
        assert "xxe_testing" in names
        assert names.index("input_validation") < names.index("xxe_testing"), (
            f"input_validation should come before xxe_testing: {names}"
        )

    def test_input_validation_triggers_xxe(self):
        """input_validation has xxe_testing in its triggers."""
        rc = _make_mock_recon(
            has_xxe=True,
            parameter_bearing_urls=["/xml/parse?doc=data"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        iv_phase = next(p for p in plan.phases if p.name == "input_validation")
        assert "xxe_testing" in iv_phase.triggers

    def test_xxe_triggers_access_control(self):
        """xxe_testing triggers include access_control."""
        rc = _make_mock_recon(has_xxe=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        xxe_phase = next(p for p in plan.phases if p.name == "xxe_testing")
        assert "access_control" in xxe_phase.triggers

    def test_xxe_triggers_ssrf(self):
        """xxe_testing triggers include ssrf_testing (XXE can do SSRF)."""
        rc = _make_mock_recon(has_xxe=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        xxe_phase = next(p for p in plan.phases if p.name == "xxe_testing")
        assert "ssrf_testing" in xxe_phase.triggers

    def test_xxe_ordered_before_template_injection(self):
        """xxe_testing at order=61 comes before template_injection at order=62."""
        rc = _make_mock_recon(
            has_xxe=True,
            tech_stack=["Flask", "Jinja2"],
            parameter_bearing_urls=["/xml/parse?doc=data", "/page?name=test"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        names = [p.name for p in plan.phases]
        assert "xxe_testing" in names
        assert "template_injection" in names
        assert names.index("xxe_testing") < names.index("template_injection"), (
            f"xxe_testing should come before template_injection: {names}"
        )


# ── Command Injection Testing Tests ────────────────────────────────────────


class TestCommandInjection:
    """Test the command_injection phase activation and tool generation."""

    def test_has_command_injection_flag_activates(self):
        """has_command_injection=True on ReconContext activates command_injection."""
        rc = _make_mock_recon(has_command_injection=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "command_injection" for p in plan.phases), (
            f"Expected command_injection in phases: {[p.name for p in plan.phases]}"
        )

    def test_cmd_injection_endpoints_list_activates(self):
        """cmd_injection_endpoints list on ReconContext activates command_injection."""
        rc = _make_mock_recon(cmd_injection_endpoints=["/cgi-bin/ping", "/exec/cmd"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "command_injection" for p in plan.phases)

    def test_subprocess_tech_activates(self):
        """subprocess in tech_stack activates command_injection."""
        rc = _make_mock_recon(tech_stack=["Python", "subprocess", "Flask"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "command_injection" for p in plan.phases)

    def test_exec_php_tech_activates(self):
        """exec (PHP) in tech_stack activates command_injection."""
        rc = _make_mock_recon(tech_stack=["PHP", "exec", "shell_exec"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "command_injection" for p in plan.phases)

    def test_runtime_exec_tech_activates(self):
        """runtime.exec in tech_stack activates command_injection."""
        rc = _make_mock_recon(tech_stack=["Java", "Runtime.exec", "Spring"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "command_injection" for p in plan.phases)

    def test_processbuilder_tech_activates(self):
        """ProcessBuilder in tech_stack activates command_injection."""
        rc = _make_mock_recon(tech_stack=["Java", "ProcessBuilder", "Tomcat"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "command_injection" for p in plan.phases)

    def test_child_process_tech_activates(self):
        """child_process in tech_stack activates command_injection."""
        rc = _make_mock_recon(tech_stack=["Node.js", "child_process.exec", "Express"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "command_injection" for p in plan.phases)

    def test_process_start_tech_activates(self):
        """process.start (.NET) in tech_stack activates command_injection."""
        rc = _make_mock_recon(tech_stack=[".NET", "process.start", "IIS"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "command_injection" for p in plan.phases)

    def test_parameter_urls_activate_cmd_injection(self):
        """Parameter-bearing URLs activate command_injection (injection vector)."""
        rc = _make_mock_recon(parameter_bearing_urls=["/ping?host=example.com"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "command_injection" for p in plan.phases)

    def test_file_upload_activates_cmd_injection(self):
        """File upload presence activates command_injection (filename-based injection)."""
        rc = _make_mock_recon(has_file_upload=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "command_injection" for p in plan.phases)

    def test_no_cmd_injection_signals_no_activation(self):
        """No command injection signals does NOT activate command_injection."""
        rc = _make_mock_recon(target_url="https://example.com")
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert not any(p.name == "command_injection" for p in plan.phases)

    def test_cmd_injection_has_tools(self):
        """Activated command_injection phase has tool tasks."""
        rc = _make_mock_recon(has_command_injection=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        cmdi_phase = next(p for p in plan.phases if p.name == "command_injection")
        assert len(cmdi_phase.tools) >= 2, (
            f"Expected 2+ command injection testing tools, got {len(cmdi_phase.tools)}"
        )

    def test_cmd_injection_depends_on_input_validation(self):
        """command_injection depends_on input_validation, so input_validation comes first."""
        rc = _make_mock_recon(
            has_command_injection=True,
            parameter_bearing_urls=["/ping?host=example.com"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        names = [p.name for p in plan.phases]
        assert "input_validation" in names
        assert "command_injection" in names
        assert names.index("input_validation") < names.index("command_injection"), (
            f"input_validation should come before command_injection: {names}"
        )

    def test_input_validation_triggers_cmd_injection(self):
        """input_validation has command_injection in its triggers."""
        rc = _make_mock_recon(
            has_command_injection=True,
            parameter_bearing_urls=["/ping?host=example.com"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        iv_phase = next(p for p in plan.phases if p.name == "input_validation")
        assert "command_injection" in iv_phase.triggers

    def test_cmd_injection_triggers_access_control(self):
        """command_injection triggers include access_control."""
        rc = _make_mock_recon(has_command_injection=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        cmdi_phase = next(p for p in plan.phases if p.name == "command_injection")
        assert "access_control" in cmdi_phase.triggers

    def test_cmd_injection_ordered_after_no_sql(self):
        """command_injection at order=67 comes after no_sql_injection at order=66."""
        rc = _make_mock_recon(
            has_command_injection=True,
            has_nosql=True,
            parameter_bearing_urls=["/ping?host=example.com", "/api/data?$where=true"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        names = [p.name for p in plan.phases]
        assert "no_sql_injection" in names
        assert "command_injection" in names
        assert names.index("no_sql_injection") < names.index("command_injection"), (
            f"no_sql_injection should come before command_injection: {names}"
        )


# ── NoSQL Injection Testing Tests ──────────────────────────────────────────


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


class TestLdapInjection:
    """Test the ldap_injection phase activation and tool generation."""

    def test_has_ldap_flag_activates(self):
        """has_ldap=True on ReconContext activates ldap_injection."""
        rc = _make_mock_recon(has_ldap=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "ldap_injection" for p in plan.phases), (
            f"Expected ldap_injection in phases: {[p.name for p in plan.phases]}"
        )

    def test_ldap_endpoints_list_activates(self):
        """ldap_endpoints list on ReconContext activates ldap_injection."""
        rc = _make_mock_recon(ldap_endpoints=["/ldap/search", "/ldap/authenticate"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "ldap_injection" for p in plan.phases)

    def test_openldap_tech_activates(self):
        """OpenLDAP in tech_stack activates ldap_injection."""
        rc = _make_mock_recon(tech_stack=["OpenLDAP", "Linux", "Apache"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "ldap_injection" for p in plan.phases)

    def test_active_directory_tech_activates(self):
        """Active Directory in tech_stack activates ldap_injection."""
        rc = _make_mock_recon(tech_stack=["Active Directory", "IIS", ".NET"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "ldap_injection" for p in plan.phases)

    def test_spring_ldap_tech_activates(self):
        """spring-ldap in tech_stack activates ldap_injection."""
        rc = _make_mock_recon(tech_stack=["Spring Boot", "spring-ldap", "Java"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "ldap_injection" for p in plan.phases)

    def test_python_ldap_tech_activates(self):
        """python-ldap in tech_stack activates ldap_injection."""
        rc = _make_mock_recon(tech_stack=["Django", "python-ldap", "Python"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "ldap_injection" for p in plan.phases)

    def test_auth_endpoints_activate_ldap(self):
        """Auth endpoints activate ldap_injection (LDAP is commonly used for auth)."""
        rc = _make_mock_recon(auth_endpoints=["/login"], has_login_page=False)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "ldap_injection" for p in plan.phases)

    def test_login_page_activates_ldap(self):
        """Login page presence activates ldap_injection (LDAP auth context)."""
        rc = _make_mock_recon(has_login_page=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "ldap_injection" for p in plan.phases)

    def test_parameter_urls_activate_ldap(self):
        """Parameter-bearing URLs activate ldap_injection (LDAP injection vector)."""
        rc = _make_mock_recon(parameter_bearing_urls=["/search?username=admin"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "ldap_injection" for p in plan.phases)

    def test_no_ldap_signals_no_activation(self):
        """No LDAP signals does NOT activate ldap_injection."""
        rc = _make_mock_recon(target_url="https://example.com")
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert not any(p.name == "ldap_injection" for p in plan.phases)

    def test_ldap_has_tools(self):
        """Activated ldap_injection phase has tool tasks."""
        rc = _make_mock_recon(has_ldap=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        ldap_phase = next(p for p in plan.phases if p.name == "ldap_injection")
        assert len(ldap_phase.tools) >= 2, (
            f"Expected 2+ LDAP testing tools, got {len(ldap_phase.tools)}"
        )

    def test_ldap_depends_on_input_validation(self):
        """ldap_injection depends_on input_validation, so input_validation comes first."""
        rc = _make_mock_recon(
            has_ldap=True,
            parameter_bearing_urls=["/search?username=admin"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        names = [p.name for p in plan.phases]
        assert "input_validation" in names
        assert "ldap_injection" in names
        assert names.index("input_validation") < names.index("ldap_injection"), (
            f"input_validation should come before ldap_injection: {names}"
        )

    def test_input_validation_triggers_ldap(self):
        """input_validation has ldap_injection in its triggers."""
        rc = _make_mock_recon(
            has_ldap=True,
            parameter_bearing_urls=["/search?username=admin"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        iv_phase = next(p for p in plan.phases if p.name == "input_validation")
        assert "ldap_injection" in iv_phase.triggers

    def test_ldap_triggers_access_control(self):
        """ldap_injection triggers include access_control."""
        rc = _make_mock_recon(has_ldap=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        ldap_phase = next(p for p in plan.phases if p.name == "ldap_injection")
        assert "access_control" in ldap_phase.triggers


# ── Cloud Metadata Probe Tests ────────────────────────────────────────────


class TestCloudMetadataProbe:
    """Test the cloud_metadata_probe phase activation and tool generation."""

    def test_aws_tech_stack_activates_cloud_probe(self):
        """AWS keywords in tech_stack activate cloud_metadata_probe."""
        rc = _make_mock_recon(tech_stack=["AWS", "Amazon Web Services", "EC2", "S3"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "cloud_metadata_probe" for p in plan.phases), (
            f"Expected cloud_metadata_probe in phases: {[p.name for p in plan.phases]}"
        )

    def test_gcp_tech_stack_activates_cloud_probe(self):
        """GCP keywords in tech_stack activate cloud_metadata_probe."""
        rc = _make_mock_recon(tech_stack=["Google Cloud", "GKE", "Cloud Run"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "cloud_metadata_probe" for p in plan.phases)

    def test_azure_tech_stack_activates_cloud_probe(self):
        """Azure keywords in tech_stack activate cloud_metadata_probe."""
        rc = _make_mock_recon(tech_stack=["Microsoft Azure", "Azure Functions", "AKS"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "cloud_metadata_probe" for p in plan.phases)

    def test_aws_abbreviation_activates_cloud_probe(self):
        """Short AWS abbreviation in tech_stack activates cloud_metadata_probe."""
        rc = _make_mock_recon(tech_stack=["node.js", "aws", "lambda"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "cloud_metadata_probe" for p in plan.phases)

    def test_no_cloud_tech_no_activation(self):
        """No cloud keywords in tech_stack does NOT activate cloud_metadata_probe."""
        rc = _make_mock_recon(tech_stack=["WordPress", "PHP", "nginx"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert not any(p.name == "cloud_metadata_probe" for p in plan.phases)

    def test_empty_tech_stack_no_activation(self):
        """Empty tech_stack does NOT activate cloud_metadata_probe."""
        rc = _make_mock_recon(tech_stack=[])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert not any(p.name == "cloud_metadata_probe" for p in plan.phases)

    def test_cloud_probe_has_tools(self):
        """Activated cloud_metadata_probe phase has tool tasks."""
        rc = _make_mock_recon(tech_stack=["AWS", "EC2"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        cloud_phase = next(p for p in plan.phases if p.name == "cloud_metadata_probe")
        assert len(cloud_phase.tools) >= 3, (
            f"Expected 3+ cloud probe tools, got {len(cloud_phase.tools)}"
        )
        tool_names = [t.tool_name for t in cloud_phase.tools]
        assert all(t == "nuclei" for t in tool_names)

    def test_cloud_probe_ordered_after_infrastructure(self):
        """cloud_metadata_probe depends_on infrastructure_scan, so infra comes first."""
        rc = _make_mock_recon(
            open_ports=[{"port": 443, "service": "https"}],
            tech_stack=["AWS", "EC2"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        names = [p.name for p in plan.phases]
        assert "infrastructure_scan" in names
        assert "cloud_metadata_probe" in names
        assert names.index("infrastructure_scan") < names.index("cloud_metadata_probe"), (
            f"infrastructure_scan should come before cloud_metadata_probe: {names}"
        )

    def test_cloud_probe_triggers_access_control(self):
        """cloud_metadata_probe has triggers that include access_control."""
        rc = _make_mock_recon(tech_stack=["AWS", "EC2"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        cloud_phase = next(p for p in plan.phases if p.name == "cloud_metadata_probe")
        assert "access_control" in cloud_phase.triggers


# ── Tool Dedup Tests ───────────────────────────────────────────────────


class TestToolDedup:
    """Test that duplicate tool+tag combinations are removed."""

    def test_dedup_same_tool_and_tags(self):
        """Same tool with same tags in different phases gets deduped."""
        phase1 = TestingPhase(
            name="auth_testing",
            order=20,
            tools=[
                ToolTask(tool_name="nuclei", args_template=["-tags", "auth,login"]),
            ],
        )
        phase2 = TestingPhase(
            name="tech_deep_scan",
            order=10,
            tools=[
                ToolTask(tool_name="nuclei", args_template=["-tags", "auth,login"]),
            ],
        )
        plan = WorkflowPlan(phases=[phase1, phase2])
        deduped = AdaptiveWorkflowPlanner.deduplicate_tools(plan)
        total_tools = sum(len(p.tools) for p in deduped.phases)
        assert total_tools == 1, f"Expected 1 tool total, got {total_tools}"

    def test_dedup_different_tools_preserved(self):
        """Different tools or tags are not removed by dedup."""
        phase1 = TestingPhase(
            name="auth_testing",
            order=20,
            tools=[
                ToolTask(tool_name="nuclei", args_template=["-tags", "auth,login"]),
            ],
        )
        phase2 = TestingPhase(
            name="input_validation",
            order=60,
            tools=[
                ToolTask(tool_name="dalfox", args_template=["url", "{target}", "--json"]),
            ],
        )
        plan = WorkflowPlan(phases=[phase1, phase2])
        deduped = AdaptiveWorkflowPlanner.deduplicate_tools(plan)
        total_tools = sum(len(p.tools) for p in deduped.phases)
        assert total_tools == 2, f"Expected 2 tools total, got {total_tools}"


# ── Orchestrator Integration Tests ─────────────────────────────────────


class TestOrchestratorIntegration:
    """Test that the planner integrates correctly with Orchestrator patterns."""

    def test_plan_as_agent_context(self):
        """The plan can be formatted as context for the LLM agent."""
        rc = _make_mock_recon(
            has_login_page=True,
            tech_stack=["WordPress"],
            parameter_bearing_urls=["/page?id=1"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        formatted = planner.format_plan_for_agent(plan)

        # The formatted plan should mention key information
        assert "auth_testing" in formatted
        assert "tech_deep_scan" in formatted

    def test_plan_summary_for_metrics(self):
        """Plan summary is serializable for observability and metrics."""
        rc = _make_mock_recon(has_login_page=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        summary = planner.get_plan_summary(plan)
        import json
        serialized = json.dumps(summary)
        assert serialized  # Must be valid JSON
        assert "auth_testing" in serialized
