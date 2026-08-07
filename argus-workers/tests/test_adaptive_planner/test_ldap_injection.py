"""Tests for TestLdapInjection from adaptive_planner."""


from orchestrator_pkg.planning.adaptive_planner import (
    AdaptiveWorkflowPlanner,
)

from .conftest import _make_mock_recon


class TestLdapInjection:
    """Test the ldap_injection phase activation and tool generation."""

    def test_has_ldap_flag_activates(self):
        """has_ldap=True on ReconContext activates ldap_injection."""
        rc = _make_mock_recon(has_ldap=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "ldap_injection" for p in plan.phases), (
            f"Expected ldap_injection in phases: {[p.name for p in plan.phases]}"
        )

    def test_ldap_endpoints_list_activates(self):
        """ldap_endpoints list on ReconContext activates ldap_injection."""
        rc = _make_mock_recon(ldap_endpoints=["/ldap/search", "/ldap/authenticate"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "ldap_injection" for p in plan.phases)

    def test_openldap_tech_activates(self):
        """OpenLDAP in tech_stack activates ldap_injection."""
        rc = _make_mock_recon(tech_stack=["OpenLDAP", "Linux", "Apache"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "ldap_injection" for p in plan.phases)

    def test_active_directory_tech_activates(self):
        """Active Directory in tech_stack activates ldap_injection."""
        rc = _make_mock_recon(tech_stack=["Active Directory", "IIS", ".NET"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "ldap_injection" for p in plan.phases)

    def test_spring_ldap_tech_activates(self):
        """spring-ldap in tech_stack activates ldap_injection."""
        rc = _make_mock_recon(tech_stack=["Spring Boot", "spring-ldap", "Java"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "ldap_injection" for p in plan.phases)

    def test_python_ldap_tech_activates(self):
        """python-ldap in tech_stack activates ldap_injection."""
        rc = _make_mock_recon(tech_stack=["Django", "python-ldap", "Python"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "ldap_injection" for p in plan.phases)

    def test_auth_endpoints_activate_ldap(self):
        """Auth endpoints activate ldap_injection (LDAP is commonly used for auth)."""
        rc = _make_mock_recon(auth_endpoints=["/login"], has_login_page=False)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "ldap_injection" for p in plan.phases)

    def test_login_page_activates_ldap(self):
        """Login page presence activates ldap_injection (LDAP auth context)."""
        rc = _make_mock_recon(has_login_page=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "ldap_injection" for p in plan.phases)

    def test_parameter_urls_activate_ldap(self):
        """Parameter-bearing URLs activate ldap_injection (LDAP injection vector)."""
        rc = _make_mock_recon(parameter_bearing_urls=["/search?username=admin"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "ldap_injection" for p in plan.phases)

    def test_no_ldap_signals_no_activation(self):
        """No LDAP signals does NOT activate ldap_injection."""
        rc = _make_mock_recon(target_url="https://example.com")
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert not any(p.name == "ldap_injection" for p in plan.phases)

    def test_ldap_has_tools(self):
        """Activated ldap_injection phase has tool tasks."""
        rc = _make_mock_recon(has_ldap=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        ldap_phase = next(p for p in plan.phases if p.name == "ldap_injection")
        assert len(ldap_phase.tools) >= 2, (
            f"Expected 2+ LDAP testing tools, got {len(ldap_phase.tools)}"
        )

    def test_ldap_depends_on_input_validation(self):
        """ldap_injection depends_on input_validation, so input_validation comes first."""
        rc = _make_mock_recon(
            has_ldap=True,
            parameter_bearing_urls=["/search?username=admin"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        names = [p.name for p in plan.phases]
        assert "input_validation" in names
        assert "ldap_injection" in names
        assert names.index("input_validation") < names.index("ldap_injection"), (
            f"input_validation should come before ldap_injection: {names}"
        )

    def test_input_validation_triggers_ldap(self):
        """input_validation has ldap_injection in its triggers."""
        rc = _make_mock_recon(
            has_ldap=True,
            parameter_bearing_urls=["/search?username=admin"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        iv_phase = next(p for p in plan.phases if p.name == "input_validation")
        assert "ldap_injection" in iv_phase.triggers

    def test_ldap_triggers_access_control(self):
        """ldap_injection triggers include access_control."""
        rc = _make_mock_recon(has_ldap=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        ldap_phase = next(p for p in plan.phases if p.name == "ldap_injection")
        assert "access_control" in ldap_phase.triggers


# ── Cloud Metadata Probe Tests ────────────────────────────────────────────
