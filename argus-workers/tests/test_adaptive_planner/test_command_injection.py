"""Tests for TestCommandInjection from adaptive_planner."""

from types import SimpleNamespace

from orchestrator_pkg.planning.adaptive_planner import (
    AdaptiveWorkflowPlanner,
    TestingPhase,
    ToolTask,
    WorkflowPlan,
)

from .conftest import _make_mock_recon


class TestCommandInjection:
    """Test the command_injection phase activation and tool generation."""

    def test_has_command_injection_flag_activates(self):
        """has_command_injection=True on ReconContext activates command_injection."""
        rc = _make_mock_recon(has_command_injection=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "command_injection" for p in plan.phases), (
            f"Expected command_injection in phases: {[p.name for p in plan.phases]}"
        )

    def test_cmd_injection_endpoints_list_activates(self):
        """cmd_injection_endpoints list on ReconContext activates command_injection."""
        rc = _make_mock_recon(cmd_injection_endpoints=["/cgi-bin/ping", "/exec/cmd"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "command_injection" for p in plan.phases)

    def test_subprocess_tech_activates(self):
        """subprocess in tech_stack activates command_injection."""
        rc = _make_mock_recon(tech_stack=["Python", "subprocess", "Flask"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "command_injection" for p in plan.phases)

    def test_exec_php_tech_activates(self):
        """exec (PHP) in tech_stack activates command_injection."""
        rc = _make_mock_recon(tech_stack=["PHP", "exec", "shell_exec"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "command_injection" for p in plan.phases)

    def test_runtime_exec_tech_activates(self):
        """runtime.exec in tech_stack activates command_injection."""
        rc = _make_mock_recon(tech_stack=["Java", "Runtime.exec", "Spring"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "command_injection" for p in plan.phases)

    def test_processbuilder_tech_activates(self):
        """ProcessBuilder in tech_stack activates command_injection."""
        rc = _make_mock_recon(tech_stack=["Java", "ProcessBuilder", "Tomcat"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "command_injection" for p in plan.phases)

    def test_child_process_tech_activates(self):
        """child_process in tech_stack activates command_injection."""
        rc = _make_mock_recon(tech_stack=["Node.js", "child_process.exec", "Express"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "command_injection" for p in plan.phases)

    def test_process_start_tech_activates(self):
        """process.start (.NET) in tech_stack activates command_injection."""
        rc = _make_mock_recon(tech_stack=[".NET", "process.start", "IIS"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "command_injection" for p in plan.phases)

    def test_parameter_urls_activate_cmd_injection(self):
        """Parameter-bearing URLs activate command_injection (injection vector)."""
        rc = _make_mock_recon(parameter_bearing_urls=["/ping?host=example.com"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "command_injection" for p in plan.phases)

    def test_file_upload_activates_cmd_injection(self):
        """File upload presence activates command_injection (filename-based injection)."""
        rc = _make_mock_recon(has_file_upload=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "command_injection" for p in plan.phases)

    def test_no_cmd_injection_signals_no_activation(self):
        """No command injection signals does NOT activate command_injection."""
        rc = _make_mock_recon(target_url="https://example.com")
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert not any(p.name == "command_injection" for p in plan.phases)

    def test_cmd_injection_has_tools(self):
        """Activated command_injection phase has tool tasks."""
        rc = _make_mock_recon(has_command_injection=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        cmdi_phase = next(p for p in plan.phases if p.name == "command_injection")
        assert len(cmdi_phase.tools) >= 2, (
            f"Expected 2+ command injection testing tools, got {len(cmdi_phase.tools)}"
        )

    def test_cmd_injection_depends_on_input_validation(self):
        """command_injection depends_on input_validation, so input_validation comes first."""
        rc = _make_mock_recon(
            has_command_injection=True,
            parameter_bearing_urls=["/ping?host=example.com"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        names = [p.name for p in plan.phases]
        assert "input_validation" in names
        assert "command_injection" in names
        assert names.index("input_validation") < names.index("command_injection"), (
            f"input_validation should come before command_injection: {names}"
        )

    def test_input_validation_triggers_cmd_injection(self):
        """input_validation has command_injection in its triggers."""
        rc = _make_mock_recon(
            has_command_injection=True,
            parameter_bearing_urls=["/ping?host=example.com"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        iv_phase = next(p for p in plan.phases if p.name == "input_validation")
        assert "command_injection" in iv_phase.triggers

    def test_cmd_injection_triggers_access_control(self):
        """command_injection triggers include access_control."""
        rc = _make_mock_recon(has_command_injection=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        cmdi_phase = next(p for p in plan.phases if p.name == "command_injection")
        assert "access_control" in cmdi_phase.triggers

    def test_cmd_injection_ordered_after_no_sql(self):
        """command_injection at order=67 comes after no_sql_injection at order=66."""
        rc = _make_mock_recon(
            has_command_injection=True,
            has_nosql=True,
            parameter_bearing_urls=["/ping?host=example.com", "/api/data?$where=true"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        names = [p.name for p in plan.phases]
        assert "no_sql_injection" in names
        assert "command_injection" in names
        assert names.index("no_sql_injection") < names.index("command_injection"), (
            f"no_sql_injection should come before command_injection: {names}"
        )


# ── NoSQL Injection Testing Tests ──────────────────────────────────────────
