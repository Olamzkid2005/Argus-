"""Tests for TestCloudMetadataProbe from adaptive_planner."""

from types import SimpleNamespace

from orchestrator_pkg.planning.adaptive_planner import (
    AdaptiveWorkflowPlanner,
    TestingPhase,
    ToolTask,
    WorkflowPlan,
)

from .conftest import _make_mock_recon


class TestCloudMetadataProbe:
    """Test the cloud_metadata_probe phase activation and tool generation."""

    def test_aws_tech_stack_activates_cloud_probe(self):
        """AWS keywords in tech_stack activate cloud_metadata_probe."""
        rc = _make_mock_recon(tech_stack=["AWS", "Amazon Web Services", "EC2", "S3"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "cloud_metadata_probe" for p in plan.phases), (
            f"Expected cloud_metadata_probe in phases: {[p.name for p in plan.phases]}"
        )

    def test_gcp_tech_stack_activates_cloud_probe(self):
        """GCP keywords in tech_stack activate cloud_metadata_probe."""
        rc = _make_mock_recon(tech_stack=["Google Cloud", "GKE", "Cloud Run"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "cloud_metadata_probe" for p in plan.phases)

    def test_azure_tech_stack_activates_cloud_probe(self):
        """Azure keywords in tech_stack activate cloud_metadata_probe."""
        rc = _make_mock_recon(tech_stack=["Microsoft Azure", "Azure Functions", "AKS"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "cloud_metadata_probe" for p in plan.phases)

    def test_aws_abbreviation_activates_cloud_probe(self):
        """Short AWS abbreviation in tech_stack activates cloud_metadata_probe."""
        rc = _make_mock_recon(tech_stack=["node.js", "aws", "lambda"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "cloud_metadata_probe" for p in plan.phases)

    def test_no_cloud_tech_no_activation(self):
        """No cloud keywords in tech_stack does NOT activate cloud_metadata_probe."""
        rc = _make_mock_recon(tech_stack=["WordPress", "PHP", "nginx"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert not any(p.name == "cloud_metadata_probe" for p in plan.phases)

    def test_empty_tech_stack_no_activation(self):
        """Empty tech_stack does NOT activate cloud_metadata_probe."""
        rc = _make_mock_recon(tech_stack=[])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert not any(p.name == "cloud_metadata_probe" for p in plan.phases)

    def test_cloud_probe_has_tools(self):
        """Activated cloud_metadata_probe phase has tool tasks."""
        rc = _make_mock_recon(tech_stack=["AWS", "EC2"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        cloud_phase = next(p for p in plan.phases if p.name == "cloud_metadata_probe")
        assert len(cloud_phase.tools) >= 3, (
            f"Expected 3+ cloud probe tools, got {len(cloud_phase.tools)}"
        )
        tool_names = [t.tool_name for t in cloud_phase.tools]
        assert all(t == "nuclei" for t in tool_names)

    def test_cloud_probe_ordered_after_infrastructure(self):
        """cloud_metadata_probe depends_on infrastructure_scan, so infra comes first."""
        rc = _make_mock_recon(
            open_ports=[{"port": 443, "service": "https"}],
            tech_stack=["AWS", "EC2"],
        )
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        names = [p.name for p in plan.phases]
        assert "infrastructure_scan" in names
        assert "cloud_metadata_probe" in names
        assert names.index("infrastructure_scan") < names.index("cloud_metadata_probe"), (
            f"infrastructure_scan should come before cloud_metadata_probe: {names}"
        )

    def test_cloud_probe_triggers_access_control(self):
        """cloud_metadata_probe has triggers that include access_control."""
        rc = _make_mock_recon(tech_stack=["AWS", "EC2"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        cloud_phase = next(p for p in plan.phases if p.name == "cloud_metadata_probe")
        assert "access_control" in cloud_phase.triggers


# ── Tool Dedup Tests ───────────────────────────────────────────────────
