"""End-to-end test: YAML circuit breaker override flows through to CircuitBreakerConfig.

Verifies that:
1. from_config(config_manager=...) reads custom values from a YAML file
2. from_config() falls back to defaults when YAML keys are missing or missing entirely
3. The ConfigManager correctly parses the tools.circuit_breaker section
4. Values flow through to the module-level CIRCUIT_BREAKER_THRESHOLD constant
"""
import os
import tempfile
from pathlib import Path

import pytest
import yaml


def _write_temp_yaml(data: dict) -> str:
    """Write a temporary YAML file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".yaml", prefix="argus_test_")
    with os.fdopen(fd, "w") as f:
        yaml.dump(data, f, default_flow_style=False)
    return path


class TestYAMLCircuitBreakerOverride:
    """Verify YAML circuit breaker values flow through to CircuitBreakerConfig."""

    def test_custom_values_from_yaml(self):
        """from_config() reads custom circuit breaker values from a YAML file."""
        from config.config_manager import ConfigManager
        from config.constants import CircuitBreakerConfig

        test_config = {
            "tools": {
                "circuit_breaker": {
                    "failure_threshold": 10,
                    "cooldown_seconds": 600,
                }
            }
        }
        yaml_path = _write_temp_yaml(test_config)
        try:
            cm = ConfigManager(yaml_path)
            cfg = CircuitBreakerConfig.from_config(config_manager=cm)
            assert cfg.failure_threshold == 10
            assert cfg.cooldown_seconds == 600
        finally:
            os.unlink(yaml_path)

    def test_fallback_on_partial_yaml(self):
        """from_config() falls back to defaults for missing keys."""
        from config.config_manager import ConfigManager
        from config.constants import CircuitBreakerConfig

        test_config = {
            "tools": {
                "circuit_breaker": {
                    "failure_threshold": 7,
                }
            }
        }
        yaml_path = _write_temp_yaml(test_config)
        try:
            cm = ConfigManager(yaml_path)
            cfg = CircuitBreakerConfig.from_config(config_manager=cm)
            assert cfg.failure_threshold == 7
            assert cfg.cooldown_seconds == 300  # fallback to default
        finally:
            os.unlink(yaml_path)

    def test_fallback_on_empty_yaml(self):
        """from_config() falls back to defaults when no circuit_breaker section exists."""
        from config.config_manager import ConfigManager
        from config.constants import CircuitBreakerConfig

        test_config = {"server": {"host": "127.0.0.1", "port": 9999}}
        yaml_path = _write_temp_yaml(test_config)
        try:
            cm = ConfigManager(yaml_path)
            cfg = CircuitBreakerConfig.from_config(config_manager=cm)
            assert cfg.failure_threshold == 3
            assert cfg.cooldown_seconds == 300
        finally:
            os.unlink(yaml_path)

    def test_fallback_on_missing_yaml(self):
        """from_config() falls back to defaults when no YAML file exists."""
        from config.config_manager import ConfigManager
        from config.constants import CircuitBreakerConfig

        nonexistent = str(Path(tempfile.gettempdir()) / "_argus_nonexistent_.yaml")
        cm = ConfigManager(nonexistent)
        cfg = CircuitBreakerConfig.from_config(config_manager=cm)
        assert cfg.failure_threshold == 3
        assert cfg.cooldown_seconds == 300

    def test_tool_runner_defaults_match_config(self):
        """Verify ToolRunner.__init__ defaults match CIRCUIT_BREAKER config constants."""
        from config.constants import CIRCUIT_BREAKER_COOLDOWN, CIRCUIT_BREAKER_THRESHOLD

        assert CIRCUIT_BREAKER_THRESHOLD == 3
        assert CIRCUIT_BREAKER_COOLDOWN == 300

        # Verify ToolRunner __init__ uses these constants (skip if deps missing)
        try:
            from tools.tool_runner import ToolRunner

            import inspect

            sig = inspect.signature(ToolRunner.__init__)
            failure_threshold_default = sig.parameters["failure_threshold"].default
            cooldown_seconds_default = sig.parameters["cooldown_seconds"].default
            assert failure_threshold_default == 3
            assert cooldown_seconds_default == 300
            assert failure_threshold_default == CIRCUIT_BREAKER_THRESHOLD
            assert cooldown_seconds_default == CIRCUIT_BREAKER_COOLDOWN
        except ImportError as e:
            pytest.skip(f"ToolRunner import skipped (environment deps): {e}")

    def test_yaml_integer_casting(self):
        """YAML values with string types are safely cast to int by from_config()."""
        from config.config_manager import ConfigManager
        from config.constants import CircuitBreakerConfig

        test_config = {
            "tools": {
                "circuit_breaker": {
                    "failure_threshold": "5",
                    "cooldown_seconds": "450",
                }
            }
        }
        yaml_path = _write_temp_yaml(test_config)
        try:
            cm = ConfigManager(yaml_path)
            cfg = CircuitBreakerConfig.from_config(config_manager=cm)
            assert cfg.failure_threshold == 5
            assert cfg.cooldown_seconds == 450
        finally:
            os.unlink(yaml_path)

    def test_actual_on_disk_yaml_matches_defaults(self):
        """Verify the actual config/argus_config.yaml values match the dataclass defaults.

        This catches silent drift if someone edits the YAML but forgets to update
        the CircuitBreakerConfig defaults in constants.py.
        """
        from config.config_manager import ConfigManager
        from config.constants import CircuitBreakerConfig

        config_path = os.path.join(os.path.dirname(__file__), "..", "config", "argus_config.yaml")
        cm = ConfigManager(config_path)
        cfg = CircuitBreakerConfig.from_config(config_manager=cm)
        default = CircuitBreakerConfig()
        assert cfg == default, (
            f"config/argus_config.yaml circuit_breaker values ({cfg}) "
            f"do not match dataclass defaults ({default}). "
            "Update CircuitBreakerConfig in constants.py if the YAML change was intentional."
        )
