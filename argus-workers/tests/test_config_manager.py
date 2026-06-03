"""Tests for config/config_manager.py

Covers:
  - ConfigManager initialization with/without config file
  - Default configuration values
  - get/set dotted key path
  - reload and reload_if_changed
  - _deep_merge behavior
  - all() returns copy
  - Singleton pattern
  - Missing YAML file fallback
  - PyYAML import error handling
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config.config_manager import (
    DEFAULT_CONFIG,
    ConfigManager,
    get_config,
)


class TestConfigManager:
    """Tests for ConfigManager class."""

    def test_init_with_defaults_when_no_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_path = os.path.join(tmpdir, "nonexistent.yaml")
            cm = ConfigManager(config_path=fake_path)
            assert cm._config == DEFAULT_CONFIG

    def test_get_existing_key(self):
        cm = ConfigManager(config_path="/nonexistent/config.yaml")
        assert cm.get("server.host") == "127.0.0.1"
        assert cm.get("server.port") == 9000

    def test_get_nonexistent_key_returns_default(self):
        cm = ConfigManager(config_path="/nonexistent/config.yaml")
        assert cm.get("nonexistent.key") is None
        assert cm.get("nonexistent.key", 42) == 42

    def test_get_nested_key(self):
        cm = ConfigManager(config_path="/nonexistent/config.yaml")
        timeout = cm.get("tools.timeouts.nuclei", 600)
        assert timeout == 600

    def test_get_circuit_breaker_defaults(self):
        cm = ConfigManager(config_path="/nonexistent/config.yaml")
        threshold = cm.get("tools.circuit_breaker.failure_threshold")
        assert threshold == 3

    def test_set_key(self):
        cm = ConfigManager(config_path="/nonexistent/config.yaml")
        cm.set("server.port", 8080)
        assert cm.get("server.port") == 8080

    def test_set_creates_nested_keys(self):
        cm = ConfigManager(config_path="/nonexistent/config.yaml")
        cm.set("custom.nested.key", "value")
        assert cm.get("custom.nested.key") == "value"

    def test_all_returns_copy(self):
        cm = ConfigManager(config_path="/nonexistent/config.yaml")
        all_config = cm.all()
        all_config["server"] = {"host": "0.0.0.0"}
        # Original should not be modified
        assert cm.get("server.host") == "127.0.0.1"

    def test_deep_merge_override(self):
        cm = ConfigManager(config_path="/nonexistent/config.yaml")
        base = {"a": 1, "b": {"c": 2, "d": 3}}
        override = {"b": {"c": 99}}
        result = cm._deep_merge(base, override)
        assert result["a"] == 1
        assert result["b"]["c"] == 99
        assert result["b"]["d"] == 3  # Preserved from base

    def test_deep_merge_new_key(self):
        cm = ConfigManager(config_path="/nonexistent/config.yaml")
        base = {"a": 1}
        override = {"b": 2}
        result = cm._deep_merge(base, override)
        assert result["a"] == 1
        assert result["b"] == 2

    def test_reload_picks_up_changes(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write("server:\n  port: 9000\n")
            config_path = f.name

        try:
            cm = ConfigManager(config_path=config_path)
            assert cm.get("server.port") == 9000

            # Modify the file
            with open(config_path, "w") as f2:
                f2.write("server:\n  port: 8080\n")

            cm.reload()
            assert cm.get("server.port") == 8080
        finally:
            os.unlink(config_path)

    def test_reload_if_changed_no_change(self):
        cm = ConfigManager(config_path="/nonexistent/config.yaml")
        # Should not raise
        cm.reload_if_changed()

    def test_reload_from_nonexistent_uses_defaults(self):
        cm = ConfigManager(config_path="/nonexistent/config.yaml")
        cm.reload()
        assert cm.get("redis.url") == "redis://localhost:6379/0"

    def test_yaml_import_error_falls_back_to_defaults(self):
        with patch.dict("sys.modules", {"yaml": None}):
            cm = ConfigManager(config_path="/nonexistent/config.yaml")
            assert cm.get("server.host") == "127.0.0.1"

    def test_with_valid_yaml(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write("server:\n  host: 0.0.0.0\n  port: 8080\n")
            config_path = f.name

        try:
            cm = ConfigManager(config_path=config_path)
            assert cm.get("server.host") == "0.0.0.0"
            assert cm.get("server.port") == 8080
            # Default values are preserved for unspecified keys
            assert cm.get("redis.url") == "redis://localhost:6379/0"
        finally:
            os.unlink(config_path)

    def test_thread_safety(self):
        import threading
        cm = ConfigManager(config_path="/nonexistent/config.yaml")
        errors = []

        def access_config():
            try:
                for _ in range(50):
                    cm.get("server.host")
                    cm.set("server.port", 9001)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=access_config) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


class TestSingleton:
    """Tests for the get_config singleton."""

    def test_singleton_returns_same_instance(self):
        c1 = get_config()
        c2 = get_config()
        assert c1 is c2

    def test_singleton_is_config_manager(self):
        assert isinstance(get_config(), ConfigManager)
