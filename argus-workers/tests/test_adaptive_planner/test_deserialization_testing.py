"""Tests for TestDeserializationTesting from adaptive_planner."""


from orchestrator_pkg.planning.adaptive_planner import (
    AdaptiveWorkflowPlanner,
)

from .conftest import _make_mock_recon


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
