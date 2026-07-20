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
