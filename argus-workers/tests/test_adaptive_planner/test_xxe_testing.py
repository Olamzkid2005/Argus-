"""Tests for TestXxeTesting from adaptive_planner."""

from types import SimpleNamespace

from orchestrator_pkg.planning.adaptive_planner import (
    AdaptiveWorkflowPlanner,
    TestingPhase,
    ToolTask,
    WorkflowPlan,
)

from .conftest import _make_mock_recon


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


# ── Path Traversal Testing Tests ───────────────────────────────────────────
