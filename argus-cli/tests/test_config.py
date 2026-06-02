"""
Tests for configuration management.
"""

import os
import tempfile
from pathlib import Path

import pytest

from argus_cli.config.settings import Config


class TestConfig:
    """Test cases for Config."""

    def test_default_values(self):
        config = Config()
        assert config.model == "gpt-4o-mini"
        assert config.provider == "openai"
        assert config.temperature == 0.3
        assert config.timeout == 300
        assert config.aggressiveness == "balanced"

    def test_feature_flags_default(self):
        config = Config()
        assert config.is_enabled("planner") is True
        assert config.is_enabled("recon") is True
        assert config.is_enabled("auth") is True
        assert config.is_enabled("api_testing") is True
        assert config.is_enabled("reporting") is True
        assert config.is_enabled("swarm") is False

    def test_env_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config = Config()
            config.config_dir = config_dir
            config.config_file = config_dir / "config.toml"
            config.sessions_db = config_dir / "sessions.db"

            os.environ["ARGUS_MODEL"] = "claude-sonnet"
            os.environ["ARGUS_TEMPERATURE"] = "0.7"

            try:
                config._apply_env()
                assert config.model == "claude-sonnet"
                assert config.temperature == 0.7
            finally:
                del os.environ["ARGUS_MODEL"]
                del os.environ["ARGUS_TEMPERATURE"]

    def test_config_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config = Config()
            config.config_dir = config_dir
            config.config_file = config_dir / "config.toml"
            config.sessions_db = config_dir / "sessions.db"
            config.model = "gpt-5"
            config.temperature = 0.5

            config.save()
            assert config_file.exists()

            loaded = Config.load(config.config_file)
            assert loaded.model == "gpt-5"
            assert loaded.temperature == 0.5
