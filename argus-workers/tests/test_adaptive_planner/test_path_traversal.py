"""Tests for TestPathTraversal from adaptive_planner."""

from types import SimpleNamespace

from orchestrator_pkg.planning.adaptive_planner import (
    AdaptiveWorkflowPlanner,
    TestingPhase,
    ToolTask,
    WorkflowPlan,
)

from .conftest import _make_mock_recon


class TestPathTraversal:
    """Test the path_traversal phase activation and tool generation."""

    def test_has_path_traversal_flag_activates(self):
        """has_path_traversal=True on ReconContext activates path_traversal."""
        rc = _make_mock_recon(has_path_traversal=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "path_traversal" for p in plan.phases), (
            f"Expected path_traversal in phases: {[p.name for p in plan.phases]}"
        )

    def test_path_traversal_endpoints_list_activates(self):
        """path_traversal_endpoints list on ReconContext activates path_traversal."""
        rc = _make_mock_recon(path_traversal_endpoints=["/read", "/download"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "path_traversal" for p in plan.phases)

    def test_file_get_contents_tech_activates(self):
        """file_get_contents in tech_stack activates path_traversal."""
        rc = _make_mock_recon(tech_stack=["PHP", "file_get_contents", "nginx"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "path_traversal" for p in plan.phases)

    def test_include_require_tech_activates(self):
        """include in tech_stack activates path_traversal."""
        rc = _make_mock_recon(tech_stack=["PHP", "include", "require", "Apache"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "path_traversal" for p in plan.phases)

    def test_fs_readfile_tech_activates(self):
        """fs.readFile in tech_stack activates path_traversal."""
        rc = _make_mock_recon(tech_stack=["Node.js", "fs.readFile", "Express"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "path_traversal" for p in plan.phases)

    def test_filereader_tech_activates(self):
        """FileReader in tech_stack activates path_traversal."""
        rc = _make_mock_recon(tech_stack=["Java", "FileReader", "Spring"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "path_traversal" for p in plan.phases)

    def test_file_readalltext_tech_activates(self):
        """File.ReadAllText in tech_stack activates path_traversal."""
        rc = _make_mock_recon(tech_stack=[".NET", "File.ReadAllText", "IIS"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "path_traversal" for p in plan.phases)

    def test_os_readfile_tech_activates(self):
        """os.ReadFile in tech_stack activates path_traversal."""
        rc = _make_mock_recon(tech_stack=["Go", "os.ReadFile", "nginx"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "path_traversal" for p in plan.phases)

    def test_param_urls_with_file_params_activate(self):
        """Parameter-bearing URLs with 'file' param activate path_traversal."""
        rc = _make_mock_recon(parameter_bearing_urls=["/read?file=document.txt"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "path_traversal" for p in plan.phases)

    def test_param_urls_with_page_params_activate(self):
        """Parameter-bearing URLs with 'page' param activate path_traversal."""
        rc = _make_mock_recon(parameter_bearing_urls=["/index.php?page=home"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "path_traversal" for p in plan.phases)

    def test_param_urls_with_path_params_activate(self):
        """Parameter-bearing URLs with 'path' param activate path_traversal."""
        rc = _make_mock_recon(parameter_bearing_urls=["/redirect?path=/files"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "path_traversal" for p in plan.phases)

    def test_file_upload_activates_path_traversal(self):
        """File upload presence activates path_traversal (traversal via upload paths)."""
        rc = _make_mock_recon(has_file_upload=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "path_traversal" for p in plan.phases)

    def test_no_path_traversal_signals_no_activation(self):
        """No path traversal signals does NOT activate path_traversal."""
        rc = _make_mock_recon(target_url="https://example.com")
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert not any(p.name == "path_traversal" for p in plan.phases)

    def test_path_traversal_has_tools(self):
        """Activated path_traversal phase has tool tasks."""
        rc = _make_mock_recon(has_path_traversal=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        pt_phase = next(p for p in plan.phases if p.name == "path_traversal")
        assert len(pt_phase.tools) >= 2, (
            f"Expected 2+ path traversal testing tools, got {len(pt_phase.tools)}"
        )

    def test_path_traversal_depends_on_input_validation(self):
        """path_traversal depends_on input_validation, so input_validation comes first."""
        rc = _make_mock_recon(
            has_path_traversal=True,
            parameter_bearing_urls=["/read?file=test.txt"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        names = [p.name for p in plan.phases]
        assert "input_validation" in names
        assert "path_traversal" in names
        assert names.index("input_validation") < names.index("path_traversal"), (
            f"input_validation should come before path_traversal: {names}"
        )

    def test_input_validation_triggers_path_traversal(self):
        """input_validation has path_traversal in its triggers."""
        rc = _make_mock_recon(
            has_path_traversal=True,
            parameter_bearing_urls=["/read?file=test.txt"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        iv_phase = next(p for p in plan.phases if p.name == "input_validation")
        assert "path_traversal" in iv_phase.triggers

    def test_path_traversal_triggers_access_control(self):
        """path_traversal triggers include access_control."""
        rc = _make_mock_recon(has_path_traversal=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        pt_phase = next(p for p in plan.phases if p.name == "path_traversal")
        assert "access_control" in pt_phase.triggers

    def test_path_traversal_triggers_file_upload(self):
        """path_traversal triggers include file_upload_scan (traversal via upload paths)."""
        rc = _make_mock_recon(has_path_traversal=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        pt_phase = next(p for p in plan.phases if p.name == "path_traversal")
        assert "file_upload_scan" in pt_phase.triggers


# ── Command Injection Testing Tests ────────────────────────────────────────
