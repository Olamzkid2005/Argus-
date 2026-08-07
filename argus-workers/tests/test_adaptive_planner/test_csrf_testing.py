"""Tests for TestCsrfTesting from adaptive_planner."""


from orchestrator_pkg.planning.adaptive_planner import (
    AdaptiveWorkflowPlanner,
)

from .conftest import _make_mock_recon


class TestCsrfTesting:
    """Test the csrf_testing phase activation and tool generation."""

    def test_has_csrf_flag_activates(self):
        """has_csrf=True on ReconContext activates csrf_testing."""
        rc = _make_mock_recon(has_csrf=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "csrf_testing" for p in plan.phases), (
            f"Expected csrf_testing in phases: {[p.name for p in plan.phases]}"
        )

    def test_form_endpoints_list_activates(self):
        """form_endpoints list on ReconContext activates csrf_testing."""
        rc = _make_mock_recon(form_endpoints=["/submit", "/contact"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "csrf_testing" for p in plan.phases)

    def test_login_page_activates_csrf(self):
        """Login page presence activates csrf_testing (auth actions need CSRF protection)."""
        rc = _make_mock_recon(has_login_page=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "csrf_testing" for p in plan.phases)

    def test_auth_endpoints_activate_csrf(self):
        """Auth endpoints activate csrf_testing."""
        rc = _make_mock_recon(auth_endpoints=["/login", "/register", "/reset-password"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "csrf_testing" for p in plan.phases)

    def test_api_endpoints_activate_csrf(self):
        """API endpoints activate csrf_testing (CSRF on APIs)."""
        rc = _make_mock_recon(has_api=True, api_endpoints=["/api/v1/users", "/api/v1/orders"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "csrf_testing" for p in plan.phases)

    def test_csrf_tech_keyword_activates(self):
        """CSRF-related keywords in tech_stack activate csrf_testing."""
        rc = _make_mock_recon(tech_stack=[".NET", "AntiforgeryToken", "Razor"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "csrf_testing" for p in plan.phases)

    def test_session_cookie_keyword_activates(self):
        """Session/cookie keywords in tech_stack activate csrf_testing."""
        rc = _make_mock_recon(tech_stack=["Django", "session", "Python"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "csrf_testing" for p in plan.phases)

    def test_no_csrf_signals_no_activation(self):
        """No CSRF signals does NOT activate csrf_testing."""
        rc = _make_mock_recon(target_url="https://example.com")
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert not any(p.name == "csrf_testing" for p in plan.phases)

    def test_csrf_has_tools(self):
        """Activated csrf_testing phase has tool tasks."""
        rc = _make_mock_recon(has_csrf=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        csrf_phase = next(p for p in plan.phases if p.name == "csrf_testing")
        assert len(csrf_phase.tools) >= 2, (
            f"Expected 2+ CSRF testing tools, got {len(csrf_phase.tools)}"
        )

    def test_csrf_depends_on_auth(self):
        """csrf_testing depends_on auth_testing and access_control."""
        rc = _make_mock_recon(
            has_csrf=True,
            has_login_page=True,
            auth_endpoints=["/login"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        names = [p.name for p in plan.phases]
        assert "auth_testing" in names
        assert "access_control" in names
        assert "csrf_testing" in names
        assert names.index("auth_testing") < names.index("csrf_testing"), (
            f"auth_testing should come before csrf_testing: {names}"
        )
        assert names.index("access_control") < names.index("csrf_testing"), (
            f"access_control should come before csrf_testing: {names}"
        )

    def test_csrf_triggers_session(self):
        """csrf_testing triggers include session_analysis."""
        rc = _make_mock_recon(has_csrf=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        csrf_phase = next(p for p in plan.phases if p.name == "csrf_testing")
        assert "session_analysis" in csrf_phase.triggers

    def test_csrf_ordered_between_access_and_rate(self):
        """csrf_testing at order=42 comes after access_control (40) but before rate_limit_testing (45)."""
        rc = _make_mock_recon(
            has_csrf=True,
            has_login_page=True,
            auth_endpoints=["/login"],
            has_api=True,
            api_endpoints=["/api/v1"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        names = [p.name for p in plan.phases]
        assert "access_control" in names
        assert "csrf_testing" in names
        assert "rate_limit_testing" in names
        assert names.index("access_control") < names.index("csrf_testing"), (
            f"access_control should come before csrf_testing: {names}"
        )
        assert names.index("csrf_testing") < names.index("rate_limit_testing"), (
            f"csrf_testing should come before rate_limit_testing: {names}"
        )


# ── Ordering Tests ─────────────────────────────────────────────────────
