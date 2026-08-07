"""Tests for TestTemplateInjection from adaptive_planner."""


from orchestrator_pkg.planning.adaptive_planner import (
    AdaptiveWorkflowPlanner,
)

from .conftest import _make_mock_recon


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
