"""Tests for TestOpenRedirect from adaptive_planner."""

from types import SimpleNamespace

from orchestrator_pkg.planning.adaptive_planner import (
    AdaptiveWorkflowPlanner,
    TestingPhase,
    ToolTask,
    WorkflowPlan,
)

from .conftest import _make_mock_recon


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
