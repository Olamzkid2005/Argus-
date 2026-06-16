"""
Tests for the runtime package — EngagementState, DecisionCheckpoint,
ExecutionEngine, DeterministicRuntime, Governance, MemoryRetriever.
"""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from runtime.decision_checkpoint import (
    DecisionCheckpoint,
    DecisionCheckpointRepository,
)
from runtime.engagement_state import EngagementState, ToolExecutionRecord
from runtime.execution_engine import ExecutionEngine
from runtime.governance import Governance
from runtime.memory import MemoryRetriever

# =========================================================================
# EngagementState Tests
# =========================================================================


class TestToolExecutionRecord:
    def test_create_record(self):
        """Test creating a ToolExecutionRecord with all fields."""
        record = ToolExecutionRecord(
            tool="nuclei",
            args={"target": "https://example.com"},
            timestamp=1234567890.0,
            result_summary="Found 3 vulns",
            token_usage=500,
            execution_cost=0.01,
            success=True,
        )
        assert record.tool == "nuclei"
        assert record.token_usage == 500
        assert record.execution_cost == 0.01
        assert record.success is True

    def test_to_dict_truncates_long_summary(self):
        """Test that to_dict truncates result_summary to 500 chars."""
        record = ToolExecutionRecord(
            tool="nuclei",
            args={},
            timestamp=1.0,
            result_summary="x" * 1000,
        )
        d = record.to_dict()
        assert len(d["result_summary"]) <= 500

    def test_to_dict_contains_all_keys(self):
        """Test that to_dict returns all expected keys."""
        record = ToolExecutionRecord(
            tool="nuclei", args={}, timestamp=1.0,
            result_summary="ok", token_usage=100, execution_cost=0.01,
            success=True, failure_state="",
        )
        d = record.to_dict()
        assert set(d.keys()) == {
            "tool", "args", "timestamp", "result_summary",
            "token_usage", "execution_cost", "success", "failure_state",
            "duration_ms",
        }


class TestEngagementState:
    def test_initial_state(self):
        """Test that EngagementState initializes with defaults."""
        state = EngagementState("eng-1")
        assert state.engagement_id == "eng-1"
        assert state.state_version == 0
        assert state.current_phase == "created"
        assert state.execution_iteration == 0
        assert state.recon_context == {}
        assert state.findings == []
        assert state.observations == []
        assert state.tool_history == []
        assert state.failed_actions == []

    def test_bump_version(self):
        """Test that _bump_version increments state_version."""
        state = EngagementState("eng-1")
        v0 = state.state_version
        state._bump_version()
        assert state.state_version == v0 + 1

    def test_add_observation_caps_at_50(self):
        """Test that observations list is capped at 50 entries."""
        state = EngagementState("eng-1")
        for i in range(60):
            state.add_observation("test", f"obs-{i}")
        assert len(state.observations) == 50
        assert state.observations[-1]["content"] == "obs-59"

    def test_add_observation_truncates_content(self):
        """Test that observation content is truncated to 2000 chars."""
        state = EngagementState("eng-1")
        long_content = "x" * 3000
        state.add_observation("test", long_content)
        assert len(state.observations[-1]["content"]) <= 2000

    def test_get_context_builds_string(self):
        """Test that get_context builds a context string from recent obs."""
        state = EngagementState("eng-1")
        state.add_observation("llm", "selected nuclei")
        state.add_observation("tool", "nuclei found XSS")
        context = state.get_context(max_entries=2)
        assert "[llm]: selected nuclei" in context
        assert "[tool]: nuclei found XSS" in context

    def test_record_tool_execution(self):
        """Test that tool execution records are appended."""
        state = EngagementState("eng-1")
        record = ToolExecutionRecord(tool="nuclei", args={}, timestamp=1.0, success=True)
        state.record_tool_execution(record)
        assert len(state.tool_history) == 1
        assert state.tool_history[0].tool == "nuclei"
        assert "nuclei" in state._last_agent_tried_tools

    def test_transition_updates_phase_and_bumps_version(self):
        """Test that transition updates current_phase and bumps version."""
        state = EngagementState("eng-1")
        v0 = state.state_version
        state.transition("scanning", "Starting scan")
        assert state.current_phase == "scanning"
        assert state.state_version == v0 + 1

    def test_safe_transition_skips_terminal_states(self):
        """Test safe_transition returns False for terminal states."""
        state = EngagementState("eng-1")
        # When no state_machine, it checks current_phase
        state.current_phase = "complete"
        result = state.safe_transition("failed", "too late")
        assert result is False

    def test_build_observation_returns_dict(self):
        """Test that build_observation returns expected structure."""
        state = EngagementState("eng-1")
        state.add_observation("test", "hello")
        obs = state.build_observation()
        assert obs["engagement_id"] == "eng-1"
        assert "recent_observations" in obs
        assert "budget_status" in obs
        assert "tried_tools" in obs

    def test_is_complete_detects_terminal_states(self):
        """Test is_complete returns True for terminal states."""
        state = EngagementState("eng-1")
        assert state.is_complete() is False
        # When no state_machine, current_state falls back to current_phase
        state.current_phase = "complete"
        assert state.is_complete() is True
        state.current_phase = "failed"
        assert state.is_complete() is True

    def test_snapshot_dict_roundtrip(self):
        """Test that to_snapshot_dict -> from_dict roundtrips correctly."""
        state = EngagementState("eng-1")
        state.add_observation("test", "data")
        state.record_tool_execution(
            ToolExecutionRecord(tool="nuclei", args={}, timestamp=1.0, success=True)
        )
        state.current_phase = "scanning"
        d = state.to_snapshot_dict()
        assert d["engagement_id"] == "eng-1"
        assert len(d["observations"]) == 1
        assert len(d["tool_history"]) == 1

        restored = EngagementState.from_dict(d)
        assert restored.engagement_id == "eng-1"
        assert len(restored.observations) == 1

    def test_to_dict_contains_summary(self):
        """Test that to_dict returns a summary (not full data)."""
        state = EngagementState("eng-1")
        state.add_observation("test", "data")
        d = state.to_dict()
        assert d["engagement_id"] == "eng-1"
        assert d["observations_count"] == 1
        # to_dict is a summary — observations themselves not included
        assert "observations" not in d

    def test_tried_tools_property(self):
        """Test the tried_tools property returns the set."""
        state = EngagementState("eng-1")
        state.mark_tool_tried("nuclei")
        state.mark_tool_tried("web_scanner")
        assert state.tried_tools == {"nuclei", "web_scanner"}

    def test_budget_delegation(self):
        """Test budget methods delegate to LoopBudgetManager."""
        state = EngagementState("eng-1")
        # Without a real budget_manager, these should work with defaults
        status = state.budget_status()
        assert isinstance(status, dict)


# =========================================================================
# DecisionCheckpoint Tests
# =========================================================================


class TestDecisionCheckpoint:
    def test_create_checkpoint(self):
        """Test creating a DecisionCheckpoint."""
        cp = DecisionCheckpoint(
            action_id="act-1",
            observation_hash="abc123",
            reasoning_hash="def456",
            selected_tool="nuclei",
            arguments={"target": "https://example.com"},
            timestamp=1000.0,
            state_version=1,
        )
        assert cp.action_id == "act-1"
        assert cp.selected_tool == "nuclei"
        assert cp.checkpoint_id is not None
        assert cp.execution_success is None

    def test_compute_hash_is_stable(self):
        """Test that compute_hash produces stable output."""
        h1 = DecisionCheckpoint.compute_hash("hello world")
        h2 = DecisionCheckpoint.compute_hash("hello world")
        assert h1 == h2
        assert len(h1) == 16  # 16 chars = first 16 of sha256 hex

    def test_from_action_creates_checkpoint(self):
        """Test creating checkpoint from an action-like object."""
        action = MagicMock()
        action.action_id = "act-2"
        action.tool = "nuclei"
        action.arguments = {"target": "x"}
        action.cost_usd = 0.05

        cp = DecisionCheckpoint.from_action(
            action=action,
            observation_context="observed data",
            reasoning="need to scan",
            state_version=2,
            engagement_id="eng-1",
        )
        assert cp.action_id == "act-2"
        assert cp.selected_tool == "nuclei"
        assert cp.tool_cost_usd == 0.05
        assert cp.engagement_id == "eng-1"

    def test_to_dict_serializes_arguments(self):
        """Test that to_dict serializes arguments as JSON string."""
        action = MagicMock()
        action.action_id = "act-3"
        action.tool = "nuclei"
        action.arguments = {"target": "x"}
        action.cost_usd = 0.0

        cp = DecisionCheckpoint.from_action(
            action=action,
            observation_context="obs",
            reasoning="reason",
            state_version=1,
        )
        d = cp.to_dict()
        assert isinstance(d["arguments"], str)
        parsed = json.loads(d["arguments"])
        assert parsed == {"target": "x"}

    def test_from_dict_deserializes_arguments(self):
        """Test that from_dict handles JSON string arguments."""
        d = {
            "action_id": "act-4",
            "observation_hash": "abc",
            "reasoning_hash": "def",
            "selected_tool": "nuclei",
            "arguments": '{"target": "https://example.com"}',
            "timestamp": 1000.0,
            "state_version": 1,
            "checkpoint_id": "cp-1",
        }
        cp = DecisionCheckpoint.from_dict(d)
        assert cp.selected_tool == "nuclei"
        assert cp.arguments == {"target": "https://example.com"}

    @patch("database.connection.db_cursor")
    def test_repository_save(self, mock_cursor):
        """Test that repository.save executes SQL."""
        repo = DecisionCheckpointRepository()
        mock_cursor.return_value.__enter__.return_value = MagicMock()

        action = MagicMock()
        action.action_id = "act-5"
        action.tool = "nuclei"
        action.arguments = {"target": "x"}
        action.cost_usd = 0.0

        cp = DecisionCheckpoint.from_action(
            action=action,
            observation_context="obs",
            reasoning="reason",
            state_version=1,
            engagement_id="eng-1",
        )
        result = repo.save(cp)
        assert result is True

    @patch("database.connection.db_cursor")
    def test_repository_get_latest(self, mock_cursor):
        """Test that repository.get_latest_for_engagement returns list."""
        mock_cursor.return_value.__enter__.return_value = MagicMock()
        mock_cursor.return_value.__enter__.return_value.fetchall.return_value = []

        repo = DecisionCheckpointRepository()
        result = repo.get_latest_for_engagement("eng-1", limit=5)
        assert result == []


# =========================================================================
# ExecutionEngine Tests
# =========================================================================


class TestExecutionEngine:
    def test_execute_runs_middleware_chain(self):
        """Test that middleware runs before tool execution."""
        tool_runner = MagicMock()
        tool_runner.run.return_value = MagicMock(success=True, stdout="ok")

        engine = ExecutionEngine(tool_runner=tool_runner)
        middleware_called = []

        def test_middleware(tool_name, args, kwargs):
            middleware_called.append((tool_name, args, kwargs))
            return (tool_name, args, kwargs)

        engine.add_middleware(test_middleware)
        engine.execute("nuclei", args=["https://example.com"])

        assert len(middleware_called) == 1
        assert middleware_called[0][0] == "nuclei"
        tool_runner.run.assert_called_once()

    def test_middleware_can_block_execution(self):
        """Test that middleware returning None blocks execution."""
        tool_runner = MagicMock()

        engine = ExecutionEngine(tool_runner=tool_runner)

        def blocking_middleware(tool_name, args, kwargs):
            return None  # Block the execution

        engine.add_middleware(blocking_middleware)
        result = engine.execute("nuclei", args=["out-of-scope"])

        assert result.success is False
        assert "Blocked by middleware" in result.stderr
        tool_runner.run.assert_not_called()

    def test_middleware_can_modify_args(self):
        """Test that middleware can modify tool_name, args, kwargs."""
        tool_runner = MagicMock()
        tool_runner.run.return_value = MagicMock(success=True, stdout="ok")

        engine = ExecutionEngine(tool_runner=tool_runner)

        def modifying_middleware(tool_name, args, kwargs):
            return ("modified_" + tool_name, ["modified_arg"], kwargs)

        engine.add_middleware(modifying_middleware)
        engine.execute("nuclei", args=["original"])
        tool_runner.run.assert_called_with("modified_nuclei", ["modified_arg"], timeout=300)

    def test_execute_records_to_engagement_state(self):
        """Test that execution records to engagement_state when provided."""
        tool_runner = MagicMock()
        tool_runner.run.return_value = MagicMock(success=True, stdout="result data")

        mock_state = MagicMock()
        engine = ExecutionEngine(tool_runner=tool_runner, engagement_state=mock_state)
        engine.execute("nuclei", args=["target"])

        mock_state.record_tool_execution.assert_called_once()
        record = mock_state.record_tool_execution.call_args[0][0]
        assert record.tool == "nuclei"
        assert record.success is True

    def test_execute_handles_tool_exception(self):
        """Test that tool exceptions are caught and returned as failed result."""
        tool_runner = MagicMock()
        tool_runner.run.side_effect = RuntimeError("Tool crashed")

        engine = ExecutionEngine(tool_runner=tool_runner)
        result = engine.execute("nuclei", args=["target"])

        assert result.success is False
        assert "Tool crashed" in result.stderr

    def test_scope_validator_middleware_auto_registered(self):
        """Test that scope validator is auto-registered as middleware."""
        from tools.scope_validator import ScopeValidator

        tool_runner = MagicMock()
        scope_val = ScopeValidator("eng-1", {"domains": ["example.com"]})
        engine = ExecutionEngine(tool_runner=tool_runner, scope_validator=scope_val)

        # Should have at least one middleware registered (scope check)
        assert len(engine._middleware) >= 1

        # Out-of-scope target should be blocked
        result = engine.execute("nuclei", args=[], target="https://evil.com")
        assert result.success is False
        assert "Blocked by middleware" in result.stderr
        tool_runner.run.assert_not_called()

    def test_scope_middleware_allows_in_scope_target(self):
        """Test that scope middleware allows in-scope targets."""
        from tools.scope_validator import ScopeValidator

        tool_runner = MagicMock()
        tool_runner.run.return_value = MagicMock(success=True, stdout="ok")
        scope_val = ScopeValidator("eng-1", {"domains": ["example.com"]})
        engine = ExecutionEngine(tool_runner=tool_runner, scope_validator=scope_val)

        result = engine.execute("nuclei", args=[], target="https://example.com/api")
        assert result.success is True
        tool_runner.run.assert_called_once()

    def test_engine_without_scope_validator_still_works(self):
        """Test that engine works normally without scope validator."""
        tool_runner = MagicMock()
        tool_runner.run.return_value = MagicMock(success=True, stdout="ok")
        engine = ExecutionEngine(tool_runner=tool_runner)

        result = engine.execute("nuclei", args=["target"])
        assert result.success is True
        # No middleware registered
        assert len(engine._middleware) == 0


# =========================================================================
# Governance Tests
# =========================================================================


class TestGovernance:
    def test_initial_state(self):
        """Test that Governance initializes with defaults."""
        g = Governance("eng-1")
        assert g.engagement_id == "eng-1"
        assert g.is_shutdown() is False
        assert g.shutdown_reason == ""
        status = g.get_status()
        assert status["engagement_id"] == "eng-1"
        assert status["is_shutdown"] is False

    def test_check_passes_normal_action(self):
        """Test that check() returns True for normal action."""
        g = Governance("eng-1")
        action = MagicMock(tool="nuclei", cost_usd=0.01)
        can_proceed, reason = g.check(action)
        assert can_proceed is True
        assert reason == ""

    def test_check_fails_on_runtime_timeout(self):
        """Test that check() fails when runtime exceeds limit."""
        # Use a governance with a very short timeout
        g = Governance("eng-1", max_runtime_seconds=0)
        action = MagicMock(tool="nuclei", cost_usd=0.01)
        can_proceed, reason = g.check(action)
        assert can_proceed is False
        assert "Runtime exceeded" in reason
        assert g.is_shutdown() is True

    def test_check_fails_on_cost_exceeded(self):
        """Test that check() fails when projected cost exceeds limit."""
        g = Governance("eng-1", max_cost_usd=0.01)
        action = MagicMock(tool="nuclei", cost_usd=0.02)
        can_proceed, reason = g.check(action)
        assert can_proceed is False
        assert "cost_guard" in reason

    def test_check_fails_on_token_exceeded(self):
        """Test that check() fails when token budget is exceeded."""
        g = Governance("eng-1", max_tokens=50)
        action = MagicMock(tool="port_scanner", cost_usd=0.0)
        can_proceed, reason = g.check(action)
        assert can_proceed is False
        assert "token_budget" in reason

    def test_record_result_tracks_cost(self):
        """Test that record_result accumulates cost."""
        g = Governance("eng-1")
        result = MagicMock(success=True)
        action = MagicMock(tool="nuclei", cost_usd=0.05)
        g.record_result(result, action)
        assert g._total_cost_usd == 0.05

    def test_low_signal_detection(self):
        """Test that consecutive low-signal results trigger threshold."""
        g = Governance("eng-1", low_signal_threshold=2)
        # Record two low-value results
        for _ in range(2):
            low_result = MagicMock(success=True)
            # No high severity findings
            low_result.findings = [{"severity": "INFO"}]
            g.record_result(low_result)

        is_low, reason = g.check_low_signal()
        assert is_low is True
        assert "Low-signal threshold reached" in reason

    def test_high_value_result_resets_low_signal(self):
        """Test that a high-value result resets the low-signal counter."""
        g = Governance("eng-1", low_signal_threshold=2)
        # One low, then one high
        low_result = MagicMock(success=True)
        low_result.findings = [{"severity": "INFO"}]
        g.record_result(low_result)

        high_result = MagicMock(success=True)
        high_result.findings = [{"severity": "CRITICAL"}]
        g.record_result(high_result)

        is_low, _ = g.check_low_signal()
        assert is_low is False  # Counter was reset

    def test_get_status_returns_snapshot(self):
        """Test that get_status returns current governance state."""
        g = Governance("eng-1")
        status = g.get_status()
        assert "runtime_elapsed_seconds" in status
        assert "max_runtime_seconds" in status
        assert "total_cost_usd" in status
        assert "total_tokens_estimated" in status
        assert "consecutive_low_signal" in status
        assert "is_shutdown" in status
        assert status["is_shutdown"] is False

    def test_shutdown_persists(self):
        """Test that once shutdown, all checks fail."""
        g = Governance("eng-1")
        g._shutdown("test_reason", "testing")
        assert g.is_shutdown() is True
        action = MagicMock(tool="nuclei", cost_usd=0.0)
        can_proceed, _ = g.check(action)
        assert can_proceed is False

    def test_reset_low_signal_counter(self):
        """Test that reset_low_signal_counter works."""
        g = Governance("eng-1")
        g._consecutive_low_signal = 3
        g.reset_low_signal_counter()
        assert g._consecutive_low_signal == 0


# =========================================================================
# MemoryRetriever Tests
# =========================================================================


class TestMemoryRetriever:
    def test_get_observation_summary_with_observations(self):
        """Test get_observation_summary with EngagementState-like object."""
        retriever = MemoryRetriever()
        state = MagicMock()
        state.observations = [
            {"role": "llm", "content": "selected tool A"},
            {"role": "tool", "content": "tool A found stuff"},
            {"role": "llm", "content": "selected tool B"},
            {"role": "tool", "content": "tool B found more"},
        ]
        state.engagement_id = "eng-1"

        summary = retriever.get_observation_summary(state, max_tokens=2000)
        assert "RECENT OBSERVATIONS" in summary
        assert "selected tool A" in summary or "selected tool B" in summary

    def test_get_observation_summary_with_history_fallback(self):
        """Test fallback to state.history when state.observations absent."""
        retriever = MemoryRetriever()
        state = MagicMock(spec=[])  # No observations attribute
        state.history = [
            {"role": "system", "content": "Task: scan"},
            {"role": "observation", "content": "ran nuclei"},
        ]
        # Remove observations to force fallback
        del state.observations
        state.engagement_id = "eng-1"

        summary = retriever.get_observation_summary(state, max_tokens=2000)
        assert "RECENT OBSERVATIONS" in summary

    def test_get_observation_summary_empty(self):
        """Test get_observation_summary with no data."""
        retriever = MemoryRetriever()
        state = MagicMock()
        state.observations = []
        state.engagement_id = ""

        # Set connection_string to None to skip DB queries
        retriever.connection_string = None
        summary = retriever.get_observation_summary(state, max_tokens=2000)
        assert summary == "" or summary is not None

    def test_get_relevant_context_structure(self):
        """Test that get_relevant_context returns 3-tier structure."""
        retriever = MemoryRetriever()
        state = MagicMock()
        state.observations = [{"role": "test", "content": "hello"}]
        state.engagement_id = "eng-1"

        context = retriever.get_relevant_context(state)
        assert "short_term" in context
        assert "medium_term" in context
        assert "long_term" in context

    def test_get_observation_summary_respects_max_tokens(self):
        """Test that get_observation_summary truncates to max_tokens."""
        retriever = MemoryRetriever()
        state = MagicMock()
        # Very long observations
        state.observations = [
            {"role": "tool", "content": "x" * 5000} for _ in range(10)
        ]
        state.engagement_id = "eng-1"

        summary = retriever.get_observation_summary(state, max_tokens=100)
        # 100 tokens * 4 chars/token = 400 chars max
        # Check it's not massively oversized
        assert len(summary) <= 500  # Allow some slack for section headers


# =========================================================================
# Integration Smoke Tests
# =========================================================================


class TestRuntimeIntegration:
    """Smoke tests that verify runtime components work together."""

    def test_engagement_state_with_execution_engine(self):
        """Test EngagementState + ExecutionEngine integration."""
        tool_runner = MagicMock()
        tool_runner.run.return_value = MagicMock(success=True, stdout="scan results")

        state = EngagementState("eng-integ-1")
        engine = ExecutionEngine(
            tool_runner=tool_runner,
            engagement_state=state,
        )

        result = engine.execute("nuclei", args=["https://example.com"])
        assert result.success is True
        assert len(state.tool_history) == 1
        assert state.tool_history[0].tool == "nuclei"

    def test_engagement_state_with_governance(self):
        """Test EngagementState + Governance interaction."""
        state = EngagementState("eng-integ-2")
        governance = Governance(
            "eng-integ-2",
            max_cost_usd=10.0,
            max_tokens=100000,
            max_runtime_seconds=3600,
        )

        # Simulate the agent loop: check, execute, record
        action = MagicMock(tool="nuclei", cost_usd=0.05)
        can_proceed, reason = governance.check(action)
        assert can_proceed is True

        result = MagicMock(success=True)
        governance.record_result(result, action)

        # State tracks tool execution
        tool_record = ToolExecutionRecord(
            tool="nuclei", args={}, timestamp=time.time(),
            result_summary="ok", success=True,
        )
        state.record_tool_execution(tool_record)
        assert len(state.tool_history) == 1
        assert governance._total_cost_usd == 0.05

    def test_decision_checkpoint_with_engagement_state(self):
        """Test DecisionCheckpoint + EngagementState integration."""
        state = EngagementState("eng-integ-3")
        state.execution_iteration = 1
        state._bump_version()

        # Create a checkpoint from an agent action
        action = MagicMock()
        action.action_id = "integ-act-1"
        action.tool = "nuclei"
        action.arguments = {"target": "https://example.com"}
        action.cost_usd = 0.01

        cp = DecisionCheckpoint.from_action(
            action=action,
            observation_context="observed data",
            reasoning="need to scan for CVEs",
            state_version=state.state_version,
            engagement_id=state.engagement_id,
        )
        assert cp.action_id == "integ-act-1"
        assert cp.selected_tool == "nuclei"
        assert cp.state_version == 1

        # Record the tool execution in state
        state.record_tool_execution(
            ToolExecutionRecord(
                tool=cp.selected_tool,
                args=cp.arguments,
                timestamp=cp.timestamp,
                success=True,
            )
        )
        assert len(state.tool_history) == 1
        assert state.state_version == 2  # bumped on record

    def test_all_components_roundtrip(self):
        """End-to-end: simulate a full agent iteration through all components."""
        # 1. Create state
        state = EngagementState("eng-integ-4")

        # 2. Governance checks and tracks
        governance = Governance("eng-integ-4", max_cost_usd=5.0)
        action = MagicMock(tool="nuclei", cost_usd=0.10)
        assert governance.check(action) == (True, "")

        # 3. Decision checkpoint
        cp = DecisionCheckpoint.from_action(
            action=action,
            observation_context="target: example.com",
            reasoning="run nuclei first",
            state_version=state.state_version,
            engagement_id=state.engagement_id,
        )
        assert cp.selected_tool == "nuclei"

        # 4. Execute via engine
        tool_runner = MagicMock()
        tool_runner.run.return_value = MagicMock(
            success=True, stdout="nuclei found XSS", tool="nuclei",
        )
        engine = ExecutionEngine(tool_runner=tool_runner, engagement_state=state)
        result = engine.execute("nuclei", args=["https://example.com"])
        assert result.success is True

        # 5. Record in governance
        governance.record_result(result, action)
        assert governance._total_cost_usd == 0.10

        # 6. Add observation
        state.add_observation("tool", "nuclei found XSS")
        assert len(state.observations) == 1

        # 7. Memory retrieval
        retriever = MemoryRetriever(connection_string=None)
        summary = retriever.get_observation_summary(state, max_tokens=500)
        assert "RECENT OBSERVATIONS" in summary or summary == ""

        # 8. Verify full state
        d = state.to_dict()
        assert d["engagement_id"] == "eng-integ-4"
        assert d["tool_history_count"] >= 1
        assert d["state_version"] >= 1


# =========================================================================
# Shadow-Mode Validation Tests
# =========================================================================


class TestShadowMode:
    def setup_method(self):
        """Reset shadow stats before each test."""
        from runtime.shadow_mode import reset_shadow_stats
        reset_shadow_stats()

    def test_matching_results(self):
        """Test that matching results increment consecutive successes."""
        from runtime.shadow_mode import get_shadow_stats, shadow_compare
        shadow_compare("test_phase", "eng-1", {"key": "value"}, lambda: {"key": "value"})
        stats = get_shadow_stats("test_phase")
        assert stats["consecutive_successes"] == 1
        assert stats["total_mismatches"] == 0

    def test_mismatching_results(self):
        """Test that mismatching results reset consecutive successes."""
        from runtime.shadow_mode import get_shadow_stats, shadow_compare
        shadow_compare("test_phase", "eng-1", {"key": "new_value"}, lambda: {"key": "old_value"})
        stats = get_shadow_stats("test_phase")
        assert stats["consecutive_successes"] == 0
        assert stats["total_mismatches"] == 1

    def test_old_path_exception(self):
        """Test that old path exceptions are counted as mismatches."""
        from runtime.shadow_mode import get_shadow_stats, shadow_compare

        def failing_old_path():
            raise RuntimeError("old path failed")

        shadow_compare("test_phase", "eng-1", {"key": "value"}, failing_old_path)
        stats = get_shadow_stats("test_phase")
        assert stats["consecutive_successes"] == 0
        assert stats["total_mismatches"] == 1

    def test_key_fields_comparison(self):
        """Test comparing only specific key fields."""
        from runtime.shadow_mode import get_shadow_stats, shadow_compare
        new_result = {"risk": "high", "findings": ["xss"]}
        old_result = {"risk": "high", "findings": ["sqli"]}
        # Compare only 'risk' key — should match
        shadow_compare("test_phase", "eng-1", new_result, lambda: old_result, key_fields=["risk"])
        stats = get_shadow_stats("test_phase")
        assert stats["consecutive_successes"] == 1

    def test_consecutive_successes_accumulate(self):
        """Test that consecutive successes accumulate across calls."""
        from runtime.shadow_mode import get_shadow_stats, shadow_compare
        for _ in range(5):
            shadow_compare("test_phase", "eng-1", {"key": "v"}, lambda: {"key": "v"})
        stats = get_shadow_stats("test_phase")
        assert stats["consecutive_successes"] == 5

    def test_mismatch_resets_consecutive(self):
        """Test that a mismatch resets the consecutive counter."""
        from runtime.shadow_mode import get_shadow_stats, shadow_compare
        for _ in range(3):
            shadow_compare("test_phase", "eng-1", {"key": "v"}, lambda: {"key": "v"})
        # Now a mismatch
        shadow_compare("test_phase", "eng-1", {"key": "new"}, lambda: {"key": "old"})
        stats = get_shadow_stats("test_phase")
        assert stats["consecutive_successes"] == 0
        assert stats["total_mismatches"] == 1

    def test_get_shadow_stats_all_phases(self):
        """Test that get_shadow_stats without phase returns all."""
        from runtime.shadow_mode import get_shadow_stats, shadow_compare
        shadow_compare("phase_a", "eng-1", {"k": "v"}, lambda: {"k": "v"})
        shadow_compare("phase_b", "eng-1", {"k": "v"}, lambda: {"k": "old"})
        all_stats = get_shadow_stats()
        assert "consecutive_successes" in all_stats
        assert "total_mismatches" in all_stats
        assert all_stats["consecutive_successes"]["phase_a"] == 1
        assert all_stats["total_mismatches"]["phase_b"] == 1

    def test_reset_shadow_stats(self):
        """Test that reset clears stats for a specific phase."""
        from runtime.shadow_mode import (
            get_shadow_stats,
            reset_shadow_stats,
            shadow_compare,
        )
        shadow_compare("test_phase", "eng-1", {"k": "v"}, lambda: {"k": "v"})
        reset_shadow_stats("test_phase")
        stats = get_shadow_stats("test_phase")
        assert stats["consecutive_successes"] == 0
        assert stats["total_mismatches"] == 0


# =========================================================================
# SafeEventEmitter (Transactional Event Stream) Tests
# =========================================================================


class TestSafeEventEmitter:
    """Tests for SafeEventEmitter — persist -> commit -> emit ordering."""

    def test_queues_events_before_flush(self):
        """Test that events are queued and not emitted until flush."""
        from runtime.event_stream import SafeEventEmitter

        emitter = SafeEventEmitter("eng-1")
        emitter.emit_thinking("test message")
        assert emitter.queue_size == 1
        emitter.emit_tool_start("nuclei", ["-u", "target"])
        assert emitter.queue_size == 2
        emitter.emit_tool_complete("nuclei", True, 100, 3)
        assert emitter.queue_size == 3

    def test_flush_emits_events(self):
        """Test that flush sends queued events via streaming layer."""
        from runtime.event_stream import SafeEventEmitter

        emitter = SafeEventEmitter("eng-1")
        emitter.emit_thinking("hello")
        emitter.emit_tool_start("nuclei", ["-u", "t"])

        # SafeEventEmitter.flush() imports streaming functions inside its scope
        with patch("streaming.emit_thinking") as mock_thinking, \
             patch("streaming.emit_tool_start") as mock_start, \
             patch("websocket_events.get_websocket_publisher", return_value=None):
            emitter.flush()

        mock_thinking.assert_called_once_with("eng-1", "hello", {})
        mock_start.assert_called_once_with("eng-1", "nuclei", ["-u", "t"])
        assert emitter.queue_size == 0

    def test_flush_empty_queue(self):
        """Test that flush does nothing when queue is empty."""
        from runtime.event_stream import SafeEventEmitter

        emitter = SafeEventEmitter("eng-1")

        with patch("streaming.emit_thinking") as mock, \
             patch("websocket_events.get_websocket_publisher", return_value=None):
            emitter.flush()

        mock.assert_not_called()

    def test_discard_clears_queue(self):
        """Test that discard() clears queue without emitting."""
        from runtime.event_stream import SafeEventEmitter

        emitter = SafeEventEmitter("eng-1")
        emitter.emit_thinking("will be discarded")
        assert emitter.queue_size == 1

        with patch("streaming.emit_thinking") as mock, \
             patch("websocket_events.get_websocket_publisher", return_value=None):
            emitter.discard()

        mock.assert_not_called()
        assert emitter.queue_size == 0

    def test_discard_after_db_failure(self):
        """Test that discard prevents phantom events when DB fails."""
        from runtime.event_stream import SafeEventEmitter

        emitter = SafeEventEmitter("eng-1")

        # Simulate: events queued, DB commit fails
        emitter.emit_tool_complete("scanner", True, 100, 5)
        emitter.emit_finding("f-1", "xss", "HIGH", 0.95, "https://x", "nuclei")

        # DB failure — discard instead of flush
        emitter.discard()
        assert emitter.queue_size == 0

    def test_emit_finding(self):
        """Test that emit_finding queues finding with correct fields."""
        from runtime.event_stream import SafeEventEmitter

        emitter = SafeEventEmitter("eng-1")
        emitter.emit_finding("f-1", "xss", "HIGH", 0.95, "https://x.com", "nuclei")

        assert emitter.queue_size == 1
        event = emitter._queue[0]
        assert event["type"] == "finding"
        assert event["data"]["finding_id"] == "f-1"
        assert event["data"]["finding_type"] == "xss"
        assert event["data"]["severity"] == "HIGH"

    def test_emit_state_change(self):
        """Test that emit_state_change queues event."""
        from runtime.event_stream import SafeEventEmitter

        emitter = SafeEventEmitter("eng-1")
        emitter.emit_state_change("init", "scanning", "start scan")

        assert emitter.queue_size == 1
        event = emitter._queue[0]
        assert event["type"] == "state_change"
        assert event["data"]["from_state"] == "init"
        assert event["data"]["to_state"] == "scanning"

    def test_emit_agent_decision(self):
        """Test that emit_agent_decision queues event."""
        from runtime.event_stream import SafeEventEmitter

        emitter = SafeEventEmitter("eng-1")
        emitter.emit_agent_decision(3, "nuclei", "Found open ports", True)

        assert emitter.queue_size == 1
        event = emitter._queue[0]
        assert event["type"] == "agent_decision"
        assert event["data"]["iteration"] == 3

    def test_flush_finding_via_websocket(self):
        """Test that findings are flushed via WebSocket publisher."""
        from runtime.event_stream import SafeEventEmitter

        emitter = SafeEventEmitter("eng-1")
        emitter.emit_finding("f-1", "xss", "HIGH", 0.95, "https://x.com", "nuclei")

        mock_ws = MagicMock()
        with patch("websocket_events.get_websocket_publisher", return_value=mock_ws), \
             patch("streaming.emit_thinking"):
            emitter.flush()

        mock_ws.publish_finding.assert_called_once_with(
            "eng-1", "f-1", "xss", "HIGH", 0.95, "https://x.com", "nuclei",
        )

    def test_flush_state_change_via_websocket(self):
        """Test that state changes are flushed via WebSocket publisher."""
        from runtime.event_stream import SafeEventEmitter

        emitter = SafeEventEmitter("eng-1")
        emitter.emit_state_change("init", "scanning")

        mock_ws = MagicMock()
        with patch("websocket_events.get_websocket_publisher", return_value=mock_ws), \
             patch("streaming.emit_thinking"):
            emitter.flush()

        mock_ws.publish_state_transition.assert_called_once_with(
            "eng-1", "init", "scanning", "",
        )

    def test_multiple_event_types_mixed(self):
        """Test that a mix of event types are all flushed correctly."""
        from runtime.event_stream import SafeEventEmitter

        emitter = SafeEventEmitter("eng-1")
        emitter.emit_thinking("analyzing")
        emitter.emit_tool_start("nuclei")
        emitter.emit_tool_complete("nuclei", True, 50)
        emitter.emit_state_change("scan", "analyze")

        mock_ws = MagicMock()
        with patch("streaming.emit_thinking") as mock_thinking, \
             patch("streaming.emit_tool_start") as mock_start, \
             patch("streaming.emit_tool_complete") as mock_complete, \
             patch("websocket_events.get_websocket_publisher", return_value=mock_ws):
            emitter.flush()

        mock_thinking.assert_called_once()
        mock_start.assert_called_once()
        mock_complete.assert_called_once()
        mock_ws.publish_state_transition.assert_called_once()

    def test_flush_handles_individual_event_failure(self):
        """Test that one failing event doesn't stop the rest from flushing."""
        from runtime.event_stream import SafeEventEmitter

        emitter = SafeEventEmitter("eng-1")
        emitter.emit_thinking("first")
        emitter.emit_tool_start("nuclei")
        emitter.emit_thinking("third")

        call_count = 0

        def _failing_emit(eid, msg, details):
            nonlocal call_count
            call_count += 1
            if call_count == 2:  # second call fails
                raise RuntimeError("stream closed")

        with patch("streaming.emit_thinking", side_effect=_failing_emit), \
             patch("streaming.emit_tool_start") as mock_start, \
             patch("websocket_events.get_websocket_publisher", return_value=None):
            emitter.flush()

        # tool_start should still be emitted even though second thinking failed
        mock_start.assert_called_once()
        assert emitter.queue_size == 0  # queue cleared either way


# =========================================================================
# Operational Gate Tests (Principle 2 — 100 consecutive engagements)
# =========================================================================


class TestOperationalGate:
    """Operational-scale tests simulating the '100 consecutive engagements'
    gate threshold required by Principle 2 before flipping a flag to default.

    These tests verify that the shadow-mode infrastructure can track
    consecutive successes across many simulated engagement runs and that
    a single mismatch resets the counter — exactly the pattern used to
    gate feature flag rollouts in production.
    """

    def setup_method(self):
        """Reset shadow stats before each test."""
        from runtime.shadow_mode import reset_shadow_stats
        reset_shadow_stats()

    @pytest.mark.parametrize("n_engagements", [1, 10, 50, 100, 200])
    def test_consecutive_engagements_pass_gate(self, n_engagements):
        """Simulate N consecutive engagements where the new and old paths
        produce identical results. After N engagements, the consecutive
        successes counter must equal N, proving the gate is met."""
        from runtime.shadow_mode import get_shadow_stats, shadow_compare

        for i in range(n_engagements):
            shadow_compare(
                "gate_test",
                f"eng-{i:04d}",
                {"status": "ok", "findings": 5, "duration_ms": 1200},
                lambda: {"status": "ok", "findings": 5, "duration_ms": 1200},
            )

        stats = get_shadow_stats("gate_test")
        assert stats["consecutive_successes"] == n_engagements
        assert stats["total_mismatches"] == 0

    @pytest.mark.parametrize("n_ok_before", [50, 99])
    def test_mismatch_resets_after_n_ok(self, n_ok_before):
        """Simulate N successful engagements, then a single mismatch.
        The consecutive counter must reset to 0 after the mismatch,
        simulating the 'gate not yet met' scenario."""
        from runtime.shadow_mode import get_shadow_stats, shadow_compare

        for i in range(n_ok_before):
            shadow_compare(
                "reset_test",
                f"eng-{i:04d}",
                {"result": "clean"},
                lambda: {"result": "clean"},
            )

        # Verify gate is N/n_ok_before OK
        stats_before = get_shadow_stats("reset_test")
        assert stats_before["consecutive_successes"] == n_ok_before

        # Now a mismatch
        shadow_compare(
            "reset_test",
            "eng-fail",
            {"result": "clean"},
            lambda: {"result": "vulnerable"},
        )

        stats_after = get_shadow_stats("reset_test")
        assert stats_after["consecutive_successes"] == 0
        assert stats_after["total_mismatches"] == 1

    def test_old_path_exception_breaks_gate(self):
        """If the old path raises during any engagement, it counts as a
        mismatch and resets the consecutive counter."""
        from runtime.shadow_mode import get_shadow_stats, shadow_compare

        # 20 good runs
        for i in range(20):
            shadow_compare(
                "exception_test", f"eng-{i:04d}",
                {"ok": True}, lambda: {"ok": True},
            )

        # Old path raises
        def failing_old():
            raise ConnectionError("database down")

        shadow_compare("exception_test", "eng-bad", {"ok": True}, failing_old)

        stats = get_shadow_stats("exception_test")
        assert stats["consecutive_successes"] == 0
        assert stats["total_mismatches"] == 1

    def test_multi_phase_gate(self):
        """Simulate multiple phases each tracking their own gate threshold.
        Phase A passes 100, Phase B only 50 — only A should be past the gate."""
        from runtime.shadow_mode import get_shadow_stats, shadow_compare

        # Phase A: 100 consecutive successes
        for i in range(100):
            shadow_compare(
                "phase_a", f"eng-{i:04d}",
                {"phase": "a", "ok": True},
                lambda: {"phase": "a", "ok": True},
            )

        # Phase B: 50 consecutive successes, then a mismatch
        for i in range(50):
            shadow_compare(
                "phase_b", f"eng-{i:04d}",
                {"phase": "b", "ok": True},
                lambda: {"phase": "b", "ok": True},
            )
        shadow_compare(
            "phase_b", "eng-fail",
            {"phase": "b", "ok": True},
            lambda: {"phase": "b", "ok": False},
        )

        # Phase C: 200 consecutive successes
        for i in range(200):
            shadow_compare(
                "phase_c", f"eng-{i:04d}",
                {"phase": "c", "result": i},
                lambda: {"phase": "c", "result": i},
            )

        all_stats = get_shadow_stats()
        assert all_stats["consecutive_successes"]["phase_a"] >= 100
        assert all_stats["consecutive_successes"]["phase_b"] == 0  # reset by mismatch
        assert all_stats["consecutive_successes"]["phase_c"] == 200
        # Phases with 0 mismatches may be absent from the dict (not inserted)
        assert all_stats["total_mismatches"].get("phase_a", 0) == 0
        assert all_stats["total_mismatches"]["phase_b"] == 1
        assert all_stats["total_mismatches"].get("phase_c", 0) == 0
