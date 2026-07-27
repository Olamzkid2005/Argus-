"""Tests for TestWebSocketTesting from adaptive_planner."""

from types import SimpleNamespace

from orchestrator_pkg.planning.adaptive_planner import (
    AdaptiveWorkflowPlanner,
    TestingPhase,
    ToolTask,
    WorkflowPlan,
)

from .conftest import _make_mock_recon


class TestWebSocketTesting:
    """Test the websocket_testing phase activation and tool generation."""

    def test_has_websocket_flag_activates_ws_testing(self):
        """has_websocket=True on ReconContext activates websocket_testing."""
        rc = _make_mock_recon(has_websocket=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "websocket_testing" for p in plan.phases), (
            f"Expected websocket_testing in phases: {[p.name for p in plan.phases]}"
        )

    def test_websocket_endpoints_list_activates_ws_testing(self):
        """websocket_endpoints list on ReconContext activates websocket_testing."""
        rc = _make_mock_recon(websocket_endpoints=["wss://example.com/ws"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "websocket_testing" for p in plan.phases)

    def test_websocket_tech_keyword_activates_ws_testing(self):
        """WebSocket keywords in tech_stack activate websocket_testing."""
        rc = _make_mock_recon(tech_stack=["Node.js", "Socket.IO", "Redis"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "websocket_testing" for p in plan.phases)

    def test_socketio_abbreviation_activates_ws_testing(self):
        """socket.io abbreviation in tech_stack activates websocket_testing."""
        rc = _make_mock_recon(tech_stack=["socket.io", "express"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "websocket_testing" for p in plan.phases)

    def test_api_endpoint_activates_ws_testing(self):
        """API endpoints trigger websocket_testing (WS often accompanies APIs)."""
        rc = _make_mock_recon(has_api=True, api_endpoints=["/api/v1/users"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert any(p.name == "websocket_testing" for p in plan.phases)

    def test_no_websocket_signals_no_activation(self):
        """No WebSocket signals does NOT activate websocket_testing."""
        rc = _make_mock_recon(tech_stack=["WordPress"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        assert not any(p.name == "websocket_testing" for p in plan.phases)

    def test_ws_testing_has_tools(self):
        """Activated websocket_testing phase has tool tasks."""
        rc = _make_mock_recon(has_websocket=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        ws_phase = next(p for p in plan.phases if p.name == "websocket_testing")
        assert len(ws_phase.tools) >= 2, (
            f"Expected 2+ WebSocket testing tools, got {len(ws_phase.tools)}"
        )

    def test_ws_testing_depends_on_api(self):
        """websocket_testing depends_on api_scan, so api_scan comes first."""
        rc = _make_mock_recon(has_api=True, api_endpoints=["/api/v1"], has_websocket=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        names = [p.name for p in plan.phases]
        assert "api_scan" in names
        assert "websocket_testing" in names
        assert names.index("api_scan") < names.index("websocket_testing"), (
            f"api_scan should come before websocket_testing: {names}"
        )

    def test_api_scan_triggers_ws_testing(self):
        """api_scan has websocket_testing in its triggers."""
        rc = _make_mock_recon(has_api=True, api_endpoints=["/api/v1"])
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        api_phase = next(p for p in plan.phases if p.name == "api_scan")
        assert "websocket_testing" in api_phase.triggers

    def test_ws_testing_triggers_include_access_control(self):
        """websocket_testing triggers include access_control."""
        rc = _make_mock_recon(has_websocket=True)
        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(rc)
        ws_phase = next(p for p in plan.phases if p.name == "websocket_testing")
        assert "access_control" in ws_phase.triggers
        assert "input_validation" in ws_phase.triggers


# ── CORS Origin Testing Tests ─────────────────────────────────────────────
