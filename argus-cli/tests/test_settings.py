"""
Tests for Config settings — edge cases not covered by e2e or test_config.

Covers:
  - _load_feature_flags with invalid/missing YAML
  - save() failure (permission error)
  - save_feature_flags
  - get_summary with/without API key
  - _apply_dict partial updates
  - is_enabled edge cases
  - to_dict API key masking
  - env var type coercion edge cases
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from argus_cli.config.settings import Config


class TestConfigSummary:
    """Tests for get_summary()."""

    def test_summary_with_api_key(self) -> None:
        config = Config()
        config.api_key = "sk-test-key-12345"
        summary = config.get_summary()
        assert "[key set]" in summary
        assert config.model in summary

    def test_summary_without_api_key(self) -> None:
        config = Config()
        config.api_key = None
        summary = config.get_summary()
        assert "[no key]" in summary

    def test_summary_includes_temperature(self) -> None:
        config = Config()
        config.temperature = 0.5
        summary = config.get_summary()
        assert "0.5" in summary or "temp" in summary

    def test_summary_includes_mode(self) -> None:
        config = Config()
        config.aggressiveness = "aggressive"
        summary = config.get_summary()
        assert "aggressive" in summary


class TestConfigEnvOverride:
    """Tests for env var type coercion edge cases."""

    def test_env_temperature_float(self) -> None:
        config = Config()
        with patch.dict("os.environ", {"ARGUS_TEMPERATURE": "0.8"}, clear=False):
            config._apply_env()
            assert config.temperature == 0.8

    def test_env_temperature_invalid(self) -> None:
        config = Config()
        original = config.temperature
        with patch.dict("os.environ", {"ARGUS_TEMPERATURE": "not-a-number"}, clear=False):
            config._apply_env()
            assert config.temperature == original  # unchanged

    def test_env_max_iterations_int(self) -> None:
        config = Config()
        with patch.dict("os.environ", {"ARGUS_MAX_ITERATIONS": "25"}, clear=False):
            config._apply_env()
            assert config.max_iterations == 25

    def test_env_max_iterations_invalid(self) -> None:
        config = Config()
        original = config.max_iterations
        with patch.dict("os.environ", {"ARGUS_MAX_ITERATIONS": "abc"}, clear=False):
            config._apply_env()
            assert config.max_iterations == original  # unchanged

    def test_env_auto_approve_true(self) -> None:
        config = Config()
        with patch.dict("os.environ", {"ARGUS_AUTO_APPROVE": "true"}, clear=False):
            config._apply_env()
            assert config.auto_approve is True

    def test_env_auto_approve_false(self) -> None:
        config = Config()
        with patch.dict("os.environ", {"ARGUS_AUTO_APPROVE": "false"}, clear=False):
            config._apply_env()
            assert config.auto_approve is False

    def test_env_verbose_1(self) -> None:
        config = Config()
        with patch.dict("os.environ", {"ARGUS_VERBOSE": "1"}, clear=False):
            config._apply_env()
            assert config.verbose is True

    def test_env_verbose_0(self) -> None:
        config = Config()
        with patch.dict("os.environ", {"ARGUS_VERBOSE": "0"}, clear=False):
            config._apply_env()
            assert config.verbose is False

    def test_unknown_env_var_ignored(self) -> None:
        config = Config()
        with patch.dict("os.environ", {"ARGUS_NONEXISTENT": "value"}, clear=False):
            config._apply_env()  # Should not raise


class TestConfigApplyDict:
    """Tests for _apply_dict()."""

    def test_partial_update(self) -> None:
        config = Config()
        config._apply_dict({"model": "claude-sonnet-4", "temperature": 0.5})
        assert config.model == "claude-sonnet-4"
        assert config.temperature == 0.5
        # Provider should remain default
        assert config.provider == "openai"

    def test_empty_dict(self) -> None:
        config = Config()
        original = config.model
        config._apply_dict({})
        assert config.model == original  # unchanged

    def test_unknown_keys_ignored(self) -> None:
        config = Config()
        config._apply_dict({"nonexistent_key": "value"})
        # Should not raise or change anything
        assert config.model == "gpt-4o-mini"


class TestConfigFeatureFlags:
    """Tests for feature flag loading and saving."""

    def test_load_feature_flags_missing_file(self) -> None:
        config = Config()
        config._load_feature_flags()  # No file exists, should not raise
        assert config.features["planner"] is True

    def test_load_feature_flags_invalid_yaml(self, tmp_path: Path) -> None:
        config = Config()
        config.config_dir = tmp_path
        # Create invalid YAML file
        flag_file = tmp_path / "features.yaml"
        flag_file.write_text("{{{ invalid_yaml }}}")
        config._load_feature_flags()  # Should not raise
        assert config.features["planner"] is True

    def test_save_feature_flags(self, tmp_path: Path) -> None:
        config = Config()
        config.config_dir = tmp_path
        config.features["test_flag"] = True
        config.save_feature_flags()
        flag_file = tmp_path / "features.yaml"
        assert flag_file.exists()

    def test_save_feature_flags_reloadable(self, tmp_path: Path) -> None:
        config = Config()
        config.config_dir = tmp_path
        config.features["custom_flag"] = True
        config.save_feature_flags()

        config2 = Config()
        config2.config_dir = tmp_path
        config2._load_feature_flags()
        assert config2.features.get("custom_flag") is True

    def test_is_enabled_custom_default(self) -> None:
        config = Config()
        assert config.is_enabled("nonexistent_flag") is False

    def test_feature_flags_merged_on_load(self, tmp_path: Path) -> None:
        """Loading feature flags should merge with defaults."""
        config = Config()
        config.config_dir = tmp_path
        config.save_feature_flags()  # Save defaults
        config.features["custom_flag"] = True
        config.save_feature_flags()

        config2 = Config()
        config2.config_dir = tmp_path
        config2._load_feature_flags()
        assert config2.features.get("planner") is True  # from defaults
        assert config2.features.get("custom_flag") is True  # from file


class TestConfigSave:
    """Tests for save() and error handling."""

    def test_save_creates_dir(self, tmp_path: Path) -> None:
        nested = tmp_path / "nested" / "config"
        config = Config()
        config.config_dir = nested
        config.config_file = nested / "config.toml"
        config.sessions_db = nested / "sessions.db"
        config.save()
        assert nested.exists()
        assert config.config_file.exists()

    def test_save_permission_error(self) -> None:
        config = Config()
        with patch("builtins.open") as mock_open:
            mock_open.side_effect = PermissionError("Permission denied")
            config.save()  # Should not raise


class TestConfigToDict:
    """Tests for to_dict()."""

    def test_to_dict_masks_api_key(self) -> None:
        config = Config()
        config.api_key = "sk-abcdefghijklmnop"
        d = config.to_dict()
        assert d["api_key"] is not None
        assert "..." in d["api_key"]
        assert d["api_key"] != "sk-abcdefghijklmnop"

    def test_to_dict_none_api_key(self) -> None:
        config = Config()
        config.api_key = None
        d = config.to_dict()
        assert d["api_key"] is None

    def test_to_dict_includes_features(self) -> None:
        config = Config()
        d = config.to_dict()
        assert "features" in d
        assert isinstance(d["features"], dict)


class TestConfigLoad:
    """Tests for Config.load()."""

    def test_load_creates_config_dir(self, tmp_path: Path) -> None:
        nested = tmp_path / "nonexistent" / "path"
        cfg = Config.load(nested / "config.toml")
        assert nested.exists()

    def test_load_from_nonexistent_file(self, tmp_path: Path) -> None:
        cfg = Config.load(tmp_path / "nonexistent.toml")
        assert cfg.provider == "openai"  # defaults

    def test_load_invalid_toml(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.toml"
        bad_file.write_text("{{{ not valid toml }}}")
        cfg = Config.load(bad_file)  # Should not raise
        assert cfg.model == "gpt-4o-mini"  # defaults preserved
