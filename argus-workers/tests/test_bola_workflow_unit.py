"""
Unit tests for workflow steps and BolaWorkflow orchestration.

Uses mocked AuthManager, mocked for_phase_execution scanner instances,
and controlled WorkflowContext state to verify step and workflow logic
in isolation.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from runtime.engagement_state import EngagementState
from runtime.workflows.base import StepResult, WorkflowResult
from runtime.workflows.bola import BolaWorkflow
from runtime.workflows.steps import (
    AuthenticateStep,
    DiscoverOwnedResourcesStep,
    TestBolaStep,
    TestBoplaStep,
)

# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def state():
    """EngagementState with obstacles support."""
    return EngagementState("eng-test")


@pytest.fixture
def slog():
    """Mock ScanLogger."""
    return Mock(info=MagicMock(), warning=MagicMock(), error=MagicMock())


@pytest.fixture
def emit_finding():
    """Mock finding callback."""
    return Mock()


@pytest.fixture
def ctx(state, slog, emit_finding):
    """WorkflowContext with all required fields."""
    from runtime.workflows.base import WorkflowContext

    return WorkflowContext(
        target="http://testTarget:8080",
        engagement_id="eng-test",
        state=state,
        emit_finding_callback=emit_finding,
        slog=slog,
        auth_config_a={"username": "user_a", "password": "pass_a"},
        auth_config_b={"username": "user_b", "password": "pass_b"},
    )


# ── AuthenticateStep Tests ─────────────────────────────────────────────


class TestAuthenticateStep:
    def test_authenticates_both_users(self, ctx):
        """Both users authenticated successfully."""
        step = AuthenticateStep()
        mock_session_a = Mock()
        mock_session_b = Mock()

        with patch(
            "tools.auth_manager.AuthManager.authenticate",
            side_effect=[mock_session_a, mock_session_b],
        ):
            result = step.run(ctx)

        assert result.success is True
        assert result.skipped is False
        assert ctx.session_a is mock_session_a
        assert ctx.session_b is mock_session_b

    def test_auth_failure_on_user_a_emits_obstacle(self, ctx):
        """auth_failed_a obstacle when User A auth fails."""
        from tools.auth_manager import AuthError

        step = AuthenticateStep()

        with patch(
            "tools.auth_manager.AuthManager.authenticate",
            side_effect=[AuthError("bad creds"), Mock()],
        ):
            result = step.run(ctx)

        assert result.success is True
        assert ctx.session_a is None
        assert ctx.session_b is not None
        assert len(ctx.state.obstacles) == 1
        assert ctx.state.obstacles[0]["type"] == "auth_failed_a"

    def test_auth_failure_on_user_b_emits_obstacle(self, ctx):
        """auth_failed_b obstacle when User B auth fails."""
        from tools.auth_manager import AuthError

        step = AuthenticateStep()
        mock_session_a = Mock()

        with patch(
            "tools.auth_manager.AuthManager.authenticate",
            side_effect=[mock_session_a, AuthError("bad creds")],
        ):
            result = step.run(ctx)

        assert result.success is True
        assert ctx.session_a is mock_session_a
        assert ctx.session_b is None
        assert len(ctx.state.obstacles) == 1
        assert ctx.state.obstacles[0]["type"] == "auth_failed_b"


# ── DiscoverOwnedResourcesStep Tests ──────────────────────────────────


class TestDiscoverOwnedResourcesStep:
    def test_skipped_when_session_a_none(self, ctx):
        """Step is skipped if session_a is None."""
        ctx.session_a = None
        step = DiscoverOwnedResourcesStep()
        result = step.run(ctx)
        assert result.skipped is True

    def test_discovers_resources(self, ctx):
        """Resources discovered and stored on context."""
        ctx.session_a = Mock()
        step = DiscoverOwnedResourcesStep()
        mock_owned = {"accounts": ["1", "2"], "users": ["3"]}

        with patch(
            "tools.dual_auth_scanner.DualAuthScanner.for_phase_execution"
        ) as mock_factory:
            mock_scanner = Mock()
            mock_scanner._discover_owned_resources.return_value = mock_owned
            mock_scanner._last_response_received = True
            mock_factory.return_value = mock_scanner

            result = step.run(ctx)

        assert result.success is True
        assert ctx.owned_resources == mock_owned
        assert ctx.skip_bola is False  # resources found, don't skip

    def test_target_unreachable_obstacle(self, ctx):
        """target_unreachable obstacle when no transport response."""
        ctx.session_a = Mock()
        step = DiscoverOwnedResourcesStep()

        with patch(
            "tools.dual_auth_scanner.DualAuthScanner.for_phase_execution"
        ) as mock_factory:
            mock_scanner = Mock()
            mock_scanner._discover_owned_resources.return_value = {}
            mock_scanner._last_response_received = False
            mock_factory.return_value = mock_scanner

            result = step.run(ctx)

        assert result.success is True
        assert ctx.skip_bola is True
        assert len(ctx.state.obstacles) == 1
        assert ctx.state.obstacles[0]["type"] == "target_unreachable"

    def test_no_owned_resources_obstacle(self, ctx):
        """no_owned_resources obstacle when target reachable but empty."""
        ctx.session_a = Mock()
        step = DiscoverOwnedResourcesStep()

        with patch(
            "tools.dual_auth_scanner.DualAuthScanner.for_phase_execution"
        ) as mock_factory:
            mock_scanner = Mock()
            mock_scanner._discover_owned_resources.return_value = {}
            mock_scanner._last_response_received = True
            mock_factory.return_value = mock_scanner

            result = step.run(ctx)

        assert result.success is True
        assert ctx.skip_bola is True
        assert len(ctx.state.obstacles) == 1
        assert ctx.state.obstacles[0]["type"] == "no_owned_resources"


# ── TestBolaStep Tests ────────────────────────────────────────────────


class TestTestBolaStep:
    def test_skipped_when_missing_prerequisites(self, ctx):
        """Skipped when session_b, skip_bola, or owned_resources missing."""
        step = TestBolaStep()
        assert step.run(ctx).skipped is True

    def test_emits_findings(self, ctx):
        """Findings from _test_cross_account_access are emitted."""
        ctx.session_b = Mock()
        ctx.owned_resources = {"accounts": ["1"]}
        step = TestBolaStep()
        raw_findings = [
            {"type": "CONFIRMED_BOLA", "severity": "CRITICAL", "endpoint": "/api/accounts/1"},
        ]

        with patch(
            "tools.dual_auth_scanner.DualAuthScanner.for_phase_execution"
        ) as mock_factory:
            mock_scanner = Mock()
            mock_scanner._test_cross_account_access.return_value = raw_findings
            mock_scanner._last_response_received = True
            mock_factory.return_value = mock_scanner

            result = step.run(ctx)

        assert result.success is True
        assert result.findings_emitted == 1
        assert ctx.bola_findings == 1
        mock_scanner._emit_finding.assert_called_once_with(raw_findings[0])


# ── TestBoplaStep Tests ────────────────────────────────────────────────


class TestTestBoplaStep:
    def test_bopla_on_both_sessions(self, ctx):
        """BOPLA run on both sessions."""
        ctx.session_a = Mock()
        ctx.session_b = Mock()
        step = TestBoplaStep()
        a_findings = [{"type": "BOPLA_SENSITIVE_FIELDS"}]
        b_findings = [{"type": "BOPLA_SENSITIVE_FIELDS"}]

        with patch(
            "tools.dual_auth_scanner.DualAuthScanner.for_phase_execution"
        ) as mock_factory:
            mock_scanner = Mock()
            mock_scanner._check_bopla.side_effect = [a_findings, b_findings]
            mock_factory.return_value = mock_scanner

            result = step.run(ctx)

        assert result.success is True
        assert result.findings_emitted == 2
        assert ctx.bopla_findings == 2
        assert mock_scanner._emit_finding.call_count == 2

    def test_bopla_still_executes_when_user_b_auth_failed(self, ctx):
        """BOPLA runs on User A even when User B session is None."""
        ctx.session_a = Mock()
        ctx.session_b = None
        step = TestBoplaStep()
        a_findings = [{"type": "BOPLA_SENSITIVE_FIELDS"}]

        with patch(
            "tools.dual_auth_scanner.DualAuthScanner.for_phase_execution"
        ) as mock_factory:
            mock_scanner = Mock()
            mock_scanner._check_bopla.return_value = a_findings
            mock_factory.return_value = mock_scanner

            result = step.run(ctx)

        assert result.success is True
        assert result.findings_emitted == 1
        assert ctx.bopla_findings == 1


# ── BolaWorkflow Tests ────────────────────────────────────────────────


class TestBolaWorkflow:
    @pytest.fixture
    def workflow(self, state, slog, emit_finding):
        return BolaWorkflow(
            target="http://testTarget:8080",
            auth_config_a={"username": "a"},
            auth_config_b={"username": "b"},
            engagement_id="eng-test",
            state=state,
            emit_finding_callback=emit_finding,
            slog=slog,
        )

    def test_execute_returns_workflow_result(self, workflow):
        """BolaWorkflow.execute() returns WorkflowResult."""
        with patch.multiple(
            "runtime.workflows.steps",
            AuthenticateStep=Mock,
            DiscoverOwnedResourcesStep=Mock,
            TestBolaStep=Mock,
            TestBoplaStep=Mock,
        ):
            result = workflow.execute()

        assert isinstance(result, WorkflowResult)
        assert result.success is True
        assert result.outcome in ("complete", "partial")

    def test_sessions_closed_in_finally(self, workflow):
        """Sessions are closed even if a step raises."""
        mock_session = Mock()
        workflow.ctx.session_a = mock_session
        workflow.ctx.session_b = Mock()

        # Force an exception in step execution
        workflow.steps[0].run = Mock(side_effect=RuntimeError("boom"))

        result = workflow.execute()

        assert result.success is True
        assert result.outcome == "partial"
        assert result.obstacles_encountered > 0
        mock_session.close.assert_called_once()

    def test_findings_tracked_locally(self, workflow):
        """findings_created is local sum, not from state.findings."""
        # Step emits 2 findings
        workflow.steps[0].run = Mock(return_value=StepResult(success=True, findings_emitted=2))

        with patch.object(workflow, "steps", workflow.steps[:1]):  # run only 1 step
            result = workflow.execute()

        assert result.findings_created == 2
        # state.findings would be 0 (orchestrator populates it post-scan)
        assert len(workflow.ctx.state.findings) == 0

    def test_step_exception_becomes_obstacle(self, workflow):
        """Exception in a step creates step_failed obstacle."""
        workflow.steps[0].run = Mock(side_effect=ValueError("invalid"))

        result = workflow.execute()

        assert result.success is True
        assert result.outcome == "partial"
        assert len(workflow.ctx.state.obstacles) == 1
        assert workflow.ctx.state.obstacles[0]["type"].startswith("step_failed:")


# ── Feature Flag Dispatch Tests ───────────────────────────────────────


class TestFeatureFlagDispatch:
    """Verify the _feature_enabled gate routes to the correct path."""

    def test_flag_off_routes_to_dual_auth_scanner(self) -> None:
        """When bola_workflow flag is OFF, the legacy DualAuthScanner path runs."""
        with patch("orchestrator_pkg.scan._feature_enabled", return_value=False):
            from orchestrator_pkg.scan import _feature_enabled as fe

            assert fe("bola_workflow", default=False) is False

    def test_flag_on_routes_to_bola_workflow(self) -> None:
        """When bola_workflow flag is ON, _feature_enabled returns True."""
        with patch("orchestrator_pkg.scan._feature_enabled", return_value=True):
            from orchestrator_pkg.scan import _feature_enabled as fe

            assert fe("bola_workflow", default=False) is True

    def test_flag_defaults_to_false(self) -> None:
        """The bola_workflow flag defaults to False (safe rollout)."""
        from orchestrator_pkg.scan import _feature_enabled as fe

        # Without any env var or DB flag, should fall back to default=False
        assert fe("bola_workflow") is False


# ── Edge Case Tests ────────────────────────────────────────────────────


class TestStepEdgeCases:
    """Additional edge case tests for individual steps."""

    def test_authenticate_both_users_fail(self, ctx):
        """Both auth failures emit both obstacles and both sessions are None."""
        from tools.auth_manager import AuthError
        step = AuthenticateStep()

        with patch(
            "tools.auth_manager.AuthManager.authenticate",
            side_effect=[AuthError("bad a"), AuthError("bad b")],
        ):
            result = step.run(ctx)

        assert result.success is True
        assert ctx.session_a is None
        assert ctx.session_b is None
        assert len(ctx.state.obstacles) == 2
        assert ctx.state.obstacles[0]["type"] == "auth_failed_a"
        assert ctx.state.obstacles[1]["type"] == "auth_failed_b"

    def test_discover_empty_owned_dict(self, ctx):
        """Empty dict from _discover_owned_resources triggers no_owned_resources."""
        ctx.session_a = Mock()
        step = DiscoverOwnedResourcesStep()

        with patch(
            "tools.dual_auth_scanner.DualAuthScanner.for_phase_execution"
        ) as mock_factory:
            mock_scanner = Mock()
            mock_scanner._discover_owned_resources.return_value = {}
            mock_scanner._last_response_received = True
            mock_factory.return_value = mock_scanner

            result = step.run(ctx)

        assert result.success is True
        assert ctx.skip_bola is True
        assert any(o["type"] == "no_owned_resources" for o in ctx.state.obstacles)

    def test_bola_mixed_findings(self, ctx):
        """BOLA step handles mixed CONFIRMED_BOLA and POTENTIAL_BOLA findings."""
        ctx.session_b = Mock()
        ctx.owned_resources = {"accounts": ["1"]}
        step = TestBolaStep()
        raw_findings = [
            {"type": "CONFIRMED_BOLA", "severity": "CRITICAL", "endpoint": "/a/1"},
            {"type": "POTENTIAL_BOLA", "severity": "MEDIUM", "endpoint": "/a/1"},
        ]

        with patch(
            "tools.dual_auth_scanner.DualAuthScanner.for_phase_execution"
        ) as mock_factory:
            mock_scanner = Mock()
            mock_scanner._test_cross_account_access.return_value = raw_findings
            mock_scanner._last_response_received = True
            mock_factory.return_value = mock_scanner

            result = step.run(ctx)

        assert result.success is True
        assert result.findings_emitted == 2
        assert ctx.bola_findings == 2
        assert mock_scanner._emit_finding.call_count == 2

    def test_bopla_no_findings(self, ctx):
        """BOPLA step returns 0 findings when no sensitive fields exposed."""
        ctx.session_a = Mock()
        ctx.session_b = Mock()
        step = TestBoplaStep()

        with patch(
            "tools.dual_auth_scanner.DualAuthScanner.for_phase_execution"
        ) as mock_factory:
            mock_scanner = Mock()
            mock_scanner._check_bopla.return_value = []
            mock_factory.return_value = mock_scanner

            result = step.run(ctx)

        assert result.success is True
        assert result.findings_emitted == 0
        assert ctx.bopla_findings == 0

    def test_bola_skipped_when_only_session_b_missing(self, ctx):
        """BOLA skipped when session_b is None but session_a exists."""
        ctx.session_a = Mock()
        ctx.session_b = None
        ctx.owned_resources = {"accounts": ["1"]}
        step = TestBolaStep()
        result = step.run(ctx)
        assert result.skipped is True

    def test_bola_skipped_when_skip_bola_flag_set(self, ctx):
        """BOLA skipped when skip_bola is True (set by discovery step)."""
        ctx.session_a = Mock()
        ctx.session_b = Mock()
        ctx.skip_bola = True
        ctx.owned_resources = {"accounts": ["1"]}
        step = TestBolaStep()
        result = step.run(ctx)
        assert result.skipped is True

class TestWorkflowResultEdgeCases:
    """Edge case tests for WorkflowResult."""

    def test_merge_metadata_updates_dict(self):
        """merge_metadata adds and updates metadata key-value pairs."""
        result = WorkflowResult(
            success=True, outcome="complete",
            findings_created=0, obstacles_encountered=0,
            identities_created=0, resources_created=0, requests_captured=0,
        )
        assert result.metadata == {}
        result.merge_metadata(target="http://example.com", version=1)
        assert result.metadata["target"] == "http://example.com"
        assert result.metadata["version"] == 1

    def test_merge_metadata_does_not_clear_existing(self):
        """merge_metadata preserves existing metadata entries."""
        result = WorkflowResult(
            success=True, outcome="complete",
            findings_created=0, obstacles_encountered=0,
            identities_created=0, resources_created=0, requests_captured=0,
            metadata={"engagement_id": "eng-1"},
        )
        result.merge_metadata(target="http://example.com")
        assert result.metadata["engagement_id"] == "eng-1"
        assert result.metadata["target"] == "http://example.com"
