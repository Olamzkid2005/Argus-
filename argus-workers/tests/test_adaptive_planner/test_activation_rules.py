"""Tests for TestActivationRules from adaptive_planner."""


from orchestrator_pkg.planning.adaptive_planner import (
    AdaptiveWorkflowPlanner,
)

from .conftest import _make_mock_recon


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


# ── CSRF Testing Tests ────────────────────────────────────────────────────
