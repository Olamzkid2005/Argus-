"""Tests for TestSsrfTesting from adaptive_planner."""


from orchestrator_pkg.planning.adaptive_planner import (
    AdaptiveWorkflowPlanner,
)

from .conftest import _make_mock_recon


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
