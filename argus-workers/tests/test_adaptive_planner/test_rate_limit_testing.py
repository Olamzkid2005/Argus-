"""Tests for TestRateLimitTesting from adaptive_planner."""


from orchestrator_pkg.planning.adaptive_planner import (
    AdaptiveWorkflowPlanner,
)

from .conftest import _make_mock_recon


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
