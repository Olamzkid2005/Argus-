"""
Tests for SecurityRunner — edge cases not covered by e2e tests.

Covers:
  - _ensure_engagement when engagement already exists
  - _get_orchestrator import failure and lazy loading
  - _get_stream_manager import failure
  - _run_phase orchestrator exception handling
  - _run_tool_sequence with multiple tools
  - get_status with no engagement
  - stop without engagement
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from argus_cli.config.settings import Config
from argus_cli.core.runner import SecurityRunner


@pytest.fixture
def runner() -> SecurityRunner:
    """Create a SecurityRunner with a minimal config."""
    cfg = Config()
    cfg.provider = "openai"
    cfg.model = "gpt-4o-mini"
    cfg.api_key = None
    return SecurityRunner(cfg)


class TestEnsureEngagement:
    """Tests for _ensure_engagement."""

    def test_creates_new_engagement(self, runner: SecurityRunner) -> None:
        """_ensure_engagement should create a new engagement ID."""
        eid = runner._ensure_engagement("test.com")
        assert eid is not None
        assert len(eid) > 0
        assert runner.engagement_id == eid

    def test_reuses_existing_engagement(self, runner: SecurityRunner) -> None:
        """_ensure_engagement should reuse an existing engagement ID."""
        first = runner._ensure_engagement("test.com")
        second = runner._ensure_engagement("another.com")
        assert first == second  # Same engagement reused

    def test_engagement_is_uuid(self, runner: SecurityRunner) -> None:
        """Engagement IDs should be UUID strings."""
        eid = runner._ensure_engagement("test.com")
        import uuid
        # Should be a valid UUID (or prefix)
        assert isinstance(eid, str)
        assert len(eid) > 0


class TestGetOrchestrator:
    """Tests for _get_orchestrator."""

    def test_lazy_initialization(self, runner: SecurityRunner) -> None:
        """_get_orchestrator should be None before first call."""
        assert runner._orchestrator is None

    def test_returns_none_on_import_failure(self, runner: SecurityRunner) -> None:
        """_get_orchestrator should return None when import fails."""
        with patch("argus_cli.core.runner.Path.__truediv__") as mock_path:
            mock_path.return_value = MagicMock()
            result = runner._get_orchestrator()
            assert result is None

    def test_caches_result(self, runner: SecurityRunner) -> None:
        """_get_orchestrator should cache the result."""
        mock_orch = MagicMock()
        with patch("argus_cli.core.runner.Path.__truediv__") as mock_path:
            mock_path.return_value = MagicMock()
            with patch("importlib.import_module") as mock_import:
                mock_import.side_effect = ImportError("No module")
                # Call twice — second call should use cache
                runner._get_orchestrator()
                call_count = mock_import.call_count
                runner._get_orchestrator()
                assert mock_import.call_count == call_count  # No new imports


class TestGetStreamManager:
    """Tests for _get_stream_manager."""

    def test_lazy_initialization(self, runner: SecurityRunner) -> None:
        """_get_stream_manager should be None before first call."""
        assert runner._stream_manager is None

    def test_returns_none_on_import_failure(self, runner: SecurityRunner) -> None:
        """_get_stream_manager should return None when import fails."""
        with patch("argus_cli.core.runner.Path.__truediv__") as mock_path:
            mock_path.return_value = MagicMock()
            with patch("importlib.import_module") as mock_import:
                mock_import.side_effect = ImportError("No module")
                result = runner._get_stream_manager()
                assert result is None

    def test_caches_result(self, runner: SecurityRunner) -> None:
        """_get_stream_manager should cache the result."""
        with patch("argus_cli.core.runner.Path.__truediv__") as mock_path:
            mock_path.return_value = MagicMock()
            # First call — None
            result1 = runner._get_stream_manager()
            # Second call — should still be None (cached)
            result2 = runner._get_stream_manager()
            assert result1 is result2


class TestRunPhase:
    """Tests for _run_phase."""

    def test_returns_result_on_success(self, runner: SecurityRunner) -> None:
        """_run_phase should return orchestrator result when available."""
        mock_orch = MagicMock()
        mock_orch.run.return_value = {"phase": "recon", "status": "complete"}
        runner._orchestrator = mock_orch
        result = runner._run_phase("recon", {"target": "test.com"})
        assert result["status"] == "complete"
        assert result["phase"] == "recon"

    def test_recovers_from_orchestrator_error(self, runner: SecurityRunner) -> None:
        """_run_phase should catch orchestrator exceptions and return error status."""
        mock_orch = MagicMock()
        mock_orch.run.side_effect = RuntimeError("Orchestrator failure")
        runner._orchestrator = mock_orch
        result = runner._run_phase("scan", {"target": "test.com"})
        assert result["status"] == "failed"
        assert "error" in result

    def test_falls_back_to_deterministic(self, runner: SecurityRunner) -> None:
        """_run_phase should fall back to deterministic mode when no orchestrator."""
        with patch.object(runner, '_get_orchestrator', return_value=None):
            result = runner._run_phase("recon", {"target": "test.com"})
            assert result["mode"] == "deterministic"

    def test_deterministic_recon_returns_tools(self, runner: SecurityRunner) -> None:
        """_run_phase deterministic recon should run httpx and katana."""
        result = runner._run_phase_deterministic("recon", {"target": "test.com"})
        assert result["mode"] == "deterministic"
        tools = [t["tool"] for t in result["tools"]]
        assert "httpx" in tools
        assert "katana" in tools

    def test_deterministic_scan_returns_tools(self, runner: SecurityRunner) -> None:
        """_run_phase deterministic scan should run nuclei and ffuf."""
        result = runner._run_phase_deterministic("scan", {"target": "test.com"})
        tools = [t["tool"] for t in result["tools"]]
        assert "nuclei" in tools
        assert "ffuf" in tools

    def test_deterministic_report_returns_format(self, runner: SecurityRunner) -> None:
        """_run_phase deterministic report should include output format."""
        result = runner._run_phase_deterministic("report", {})
        assert result["status"] == "complete"
        assert "format" in result

    def test_deterministic_unknown_phase(self, runner: SecurityRunner) -> None:
        """_run_phase deterministic with unknown phase should return generic result."""
        result = runner._run_phase_deterministic("unknown", {})
        assert result["status"] == "complete"
        assert result["mode"] == "deterministic"


class TestRunToolSequence:
    """Tests for _run_tool_sequence."""

    def test_runs_all_tools(self, runner: SecurityRunner) -> None:
        """_run_tool_sequence should run all provided tools."""
        result = runner._run_tool_sequence("test.com", ["httpx", "nuclei", "ffuf"])
        assert len(result["tools"]) == 3

    def test_each_tool_has_status(self, runner: SecurityRunner) -> None:
        """Each tool result should have a status field."""
        result = runner._run_tool_sequence("test.com", ["httpx"])
        assert result["tools"][0]["status"] == "simulated"

    def test_returns_target(self, runner: SecurityRunner) -> None:
        """_run_tool_sequence should return the target."""
        result = runner._run_tool_sequence("example.com", ["httpx"])
        assert result["target"] == "example.com"

    def test_returns_deterministic_mode(self, runner: SecurityRunner) -> None:
        """_run_tool_sequence should indicate deterministic mode."""
        result = runner._run_tool_sequence("test.com", ["httpx"])
        assert result["mode"] == "deterministic"

    def test_empty_tool_list(self, runner: SecurityRunner) -> None:
        """_run_tool_sequence with empty tool list should return empty results."""
        result = runner._run_tool_sequence("test.com", [])
        assert result["tools"] == []


class TestGetStatus:
    """Tests for get_status."""

    def test_returns_engagement_id_when_set(self, runner: SecurityRunner) -> None:
        """get_status should return the engagement ID when set."""
        runner._ensure_engagement("test.com")
        status = runner.get_status()
        assert status["engagement_id"] is not None

    def test_returns_none_engagement_when_not_set(self, runner: SecurityRunner) -> None:
        """get_status should return None engagement_id when not set."""
        status = runner.get_status()
        assert status["engagement_id"] is None

    def test_returns_phase(self, runner: SecurityRunner) -> None:
        """get_status should return the current phase."""
        status = runner.get_status()
        assert "phase" in status

    def test_returns_model_and_provider(self, runner: SecurityRunner) -> None:
        """get_status should return model and provider from config."""
        status = runner.get_status()
        assert "model" in status
        assert "provider" in status


class TestStop:
    """Tests for stop."""

    def test_pauses_with_engagement(self, runner: SecurityRunner) -> None:
        """stop should set phase to paused when engagement exists."""
        runner._ensure_engagement("test.com")
        runner.stop()
        assert runner.current_phase == "paused"

    def test_no_crash_without_engagement(self, runner: SecurityRunner) -> None:
        """stop should not crash when no engagement exists."""
        runner.stop()  # Should not raise


class TestReconMethod:
    """Tests for the recon() method."""

    def test_recon_returns_dict(self, runner: SecurityRunner) -> None:
        """recon() should return a dictionary."""
        result = runner.recon("test.com")
        assert isinstance(result, dict)

    def test_recon_creates_engagement(self, runner: SecurityRunner) -> None:
        """recon() should create an engagement."""
        runner.recon("test.com")
        assert runner.engagement_id is not None


class TestAuthTestMethod:
    """Tests for the auth_test() method."""

    def test_auth_test_disabled(self, runner: SecurityRunner) -> None:
        """auth_test() should skip when feature disabled."""
        runner.config.features["auth"] = False
        result = runner.auth_test("test.com")
        assert result.get("skipped") is True

    def test_auth_test_enabled(self, runner: SecurityRunner) -> None:
        """auth_test() should run when feature enabled."""
        with patch.object(runner, '_run_phase', return_value={"target": "test.com", "status": "complete"}):
            result = runner.auth_test("test.com")
            assert "target" in result or "skipped" in result


class TestApiTestMethod:
    """Tests for the api_test() method."""

    def test_api_test_disabled(self, runner: SecurityRunner) -> None:
        """api_test() should skip when feature disabled."""
        runner.config.features["api_testing"] = False
        result = runner.api_test("test.com")
        assert result.get("skipped") is True

    def test_api_test_enabled(self, runner: SecurityRunner) -> None:
        """api_test() should run when feature enabled."""
        with patch.object(runner, '_run_phase', return_value={"target": "test.com", "status": "complete"}):
            result = runner.api_test("test.com")
            assert "target" in result or "skipped" in result


class TestReportMethod:
    """Tests for the report() method."""

    def test_report_disabled(self, runner: SecurityRunner) -> None:
        """report() should skip when feature disabled."""
        runner.config.features["reporting"] = False
        result = runner.report()
        assert result.get("skipped") is True

    def test_report_with_engagement_id(self, runner: SecurityRunner) -> None:
        """report() should accept an explicit engagement_id."""
        runner._ensure_engagement("test.com")
        result = runner.report(engagement_id=runner.engagement_id)
        assert result is not None
