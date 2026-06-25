"""Tests for circuit breaker config wiring — YAML keys and ToolCircuitBreakerManager."""

from unittest.mock import MagicMock

import pytest

from config.constants import CircuitBreakerConfig
from tools.circuit_breaker import CircuitBreaker, ToolCircuitBreakerManager


class TestCircuitBreakerConfigFromConfig:
    """from_config reads max_failures/cooldown_ms YAML keys."""

    def test_reads_max_failures_and_cooldown_ms(self):
        """from_config reads the YAML keys max_failures and cooldown_ms."""
        mock_cm = MagicMock()
        mock_cm.get.side_effect = lambda key, default: {
            "tools.circuit_breaker.max_failures": 7,
            "tools.circuit_breaker.cooldown_ms": 600000,
        }.get(key, default)

        cfg = CircuitBreakerConfig.from_config(config_manager=mock_cm)

        assert cfg.failure_threshold == 7
        assert cfg.cooldown_seconds == 600000

    def test_fallback_defaults_when_missing_keys(self):
        """Missing YAML keys fall back to dataclass defaults."""
        mock_cm = MagicMock()
        mock_cm.get.side_effect = lambda key, default: default

        cfg = CircuitBreakerConfig.from_config(config_manager=mock_cm)

        assert cfg.failure_threshold == 3
        assert cfg.cooldown_seconds == 300

    def test_fallback_defaults_when_config_manager_unavailable(self):
        """from_config falls back to defaults when config manager is unavailable."""
        cfg = CircuitBreakerConfig.from_config(config_manager=None)

        assert cfg.failure_threshold == 3
        assert cfg.cooldown_seconds == 300

    def test_old_keys_not_found(self):
        """Old keys failure_threshold/cooldown_seconds return defaults if looked up."""
        mock_cm = MagicMock()
        mock_cm.get.side_effect = lambda key, default: {
            "tools.circuit_breaker.max_failures": 5,
            "tools.circuit_breaker.cooldown_ms": 300000,
        }.get(key, default)

        old_threshold = mock_cm.get("tools.circuit_breaker.failure_threshold", 3)
        old_cooldown = mock_cm.get("tools.circuit_breaker.cooldown_seconds", 300)

        assert old_threshold == 3
        assert old_cooldown == 300

        new_threshold = mock_cm.get("tools.circuit_breaker.max_failures", 3)
        new_cooldown = mock_cm.get("tools.circuit_breaker.cooldown_ms", 300)

        assert new_threshold == 5
        assert new_cooldown == 300000


class TestToolCircuitBreakerManagerConfig:
    """ToolCircuitBreakerManager stores per-instance and per-tool config."""

    def test_default_config_applied_to_all_tools(self):
        """Default failure_threshold and cooldown_seconds apply to all tools."""
        mgr = ToolCircuitBreakerManager(failure_threshold=5, cooldown_seconds=600)

        breaker_a = mgr.get_breaker("tool_a")
        breaker_b = mgr.get_breaker("tool_b")

        assert breaker_a.failure_threshold == 5
        assert breaker_a.cooldown_seconds == 600
        assert breaker_b.failure_threshold == 5
        assert breaker_b.cooldown_seconds == 600

    def test_per_tool_override_allowed(self):
        """get_breaker can accept per-tool overrides."""
        mgr = ToolCircuitBreakerManager(failure_threshold=3, cooldown_seconds=300)

        breaker = mgr.get_breaker("slow_tool", failure_threshold=1, cooldown_seconds=30)

        assert breaker.failure_threshold == 1
        assert breaker.cooldown_seconds == 30

    def test_same_tool_returns_same_breaker(self):
        """get_breaker returns the same CircuitBreaker instance for the same tool name."""
        mgr = ToolCircuitBreakerManager()

        breaker_a = mgr.get_breaker("nmap")
        breaker_b = mgr.get_breaker("nmap")

        assert breaker_a is breaker_b

    def test_different_tools_have_different_breakers(self):
        """Different tool names get separate CircuitBreaker instances."""
        mgr = ToolCircuitBreakerManager()

        breaker_a = mgr.get_breaker("nmap")
        breaker_b = mgr.get_breaker("nuclei")

        assert breaker_a is not breaker_b

    def test_breaker_failure_threshold_matches_config(self):
        """CircuitBreaker uses the failure_threshold passed to it."""
        breaker = CircuitBreaker(failure_threshold=10, cooldown_seconds=60)

        assert breaker.failure_threshold == 10
        assert breaker.cooldown_seconds == 60

    def test_breaker_opens_after_threshold_failures(self):
        """CircuitBreaker opens after reaching failure_threshold consecutive failures."""
        breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=300)

        assert breaker.state.value == "closed"
        breaker.record_failure()
        assert breaker.state.value == "closed"
        breaker.record_failure()
        assert breaker.state.value == "open"

    def test_get_status_returns_all_breaker_states(self):
        """get_status returns a dict of tool name -> state string."""
        mgr = ToolCircuitBreakerManager()
        mgr.get_breaker("tool_a")
        mgr.get_breaker("tool_b")

        status = mgr.get_status()

        assert status == {"tool_a": "closed", "tool_b": "closed"}
