"""
Tests for core constants — structural validation not covered by e2e.

Covers:
  - Path constants structure
  - THEME keys
  - Tool lists (CORE_TOOLS, PHASE2_TOOLS, PHASE3_TOOLS)
  - PHASES list matches VALID_TRANSITIONS keys
  - PROVIDERS structure
  - DEFAULT_FEATURES keys
"""

from __future__ import annotations

from pathlib import Path

import pytest

from argus_cli.core.constants import (
    APP_AUTHOR,
    APP_NAME,
    CONFIG_DIR,
    CONFIG_FILE,
    CORE_TOOLS,
    DATA_DIR,
    DEFAULT_AGGRESSIVENESS,
    DEFAULT_FEATURES,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    DEFAULT_TEMPERATURE,
    DEFAULT_TIMEOUT,
    FEATURE_FLAGS_FILE,
    PHASE2_TOOLS,
    PHASE3_TOOLS,
    PHASES,
    PROVIDERS,
    SESSIONS_DB,
    THEME,
    VALID_TRANSITIONS,
    VERSION,
)


class TestAppInfo:
    """Tests for app info constants."""

    def test_app_name_is_string(self) -> None:
        assert isinstance(APP_NAME, str)
        assert len(APP_NAME) > 0

    def test_author_is_string(self) -> None:
        assert isinstance(APP_AUTHOR, str)

    def test_version_is_string(self) -> None:
        assert isinstance(VERSION, str)
        assert "." in VERSION


class TestPathConstants:
    """Tests for path constants."""

    def test_config_dir_is_path(self) -> None:
        assert isinstance(CONFIG_DIR, Path)

    def test_data_dir_is_path(self) -> None:
        assert isinstance(DATA_DIR, Path)

    def test_sessions_db_is_path(self) -> None:
        assert isinstance(SESSIONS_DB, Path)

    def test_config_file_is_path(self) -> None:
        assert isinstance(CONFIG_FILE, Path)

    def test_feature_flags_file_is_path(self) -> None:
        assert isinstance(FEATURE_FLAGS_FILE, Path)

    def test_session_db_inside_data_dir(self) -> None:
        """sessions.db should be inside DATA_DIR."""
        assert str(SESSIONS_DB).startswith(str(DATA_DIR))

    def test_config_file_inside_config_dir(self) -> None:
        """config.toml should be inside CONFIG_DIR."""
        assert str(CONFIG_FILE).startswith(str(CONFIG_DIR))


class TestDefaults:
    """Tests for default values."""

    def test_default_model(self) -> None:
        assert isinstance(DEFAULT_MODEL, str)
        assert "gpt" in DEFAULT_MODEL

    def test_default_provider(self) -> None:
        assert DEFAULT_PROVIDER == "openai"

    def test_default_temperature(self) -> None:
        assert 0 < DEFAULT_TEMPERATURE < 1

    def test_default_max_iterations(self) -> None:
        assert DEFAULT_MAX_ITERATIONS > 0

    def test_default_timeout(self) -> None:
        assert DEFAULT_TIMEOUT > 0

    def test_default_aggressiveness(self) -> None:
        assert DEFAULT_AGGRESSIVENESS in ("passive", "balanced", "aggressive")


class TestTheme:
    """Tests for THEME styling constants."""

    def test_has_all_expected_keys(self) -> None:
        expected = {
            "primary", "secondary", "accent", "error",
            "warning", "info", "success", "dim", "highlight",
        }
        assert set(THEME.keys()) == expected

    def test_all_values_are_strings(self) -> None:
        for value in THEME.values():
            assert isinstance(value, str)
            assert len(value) > 0


class TestToolLists:
    """Tests for tool registry lists."""

    def test_core_tools_are_strings(self) -> None:
        assert len(CORE_TOOLS) > 0
        for tool in CORE_TOOLS:
            assert isinstance(tool, str)

    def test_phase2_tools_are_strings(self) -> None:
        assert len(PHASE2_TOOLS) > 0
        for tool in PHASE2_TOOLS:
            assert isinstance(tool, str)

    def test_phase3_tools_are_strings(self) -> None:
        assert len(PHASE3_TOOLS) > 0
        for tool in PHASE3_TOOLS:
            assert isinstance(tool, str)

    def test_no_duplicate_tools_across_phases(self) -> None:
        all_tools = CORE_TOOLS + PHASE2_TOOLS + PHASE3_TOOLS
        assert len(all_tools) == len(set(all_tools))

    def test_nuclei_in_core(self) -> None:
        assert "nuclei" in CORE_TOOLS

    def test_httpx_in_core(self) -> None:
        assert "httpx" in CORE_TOOLS

    def test_sqlmap_in_phase2(self) -> None:
        assert "sqlmap" in PHASE2_TOOLS

    def test_semgrep_in_phase3(self) -> None:
        assert "semgrep" in PHASE3_TOOLS


class TestPhases:
    """Tests for phase constants."""

    def test_phases_list_matches_transitions_keys(self) -> None:
        assert set(PHASES) == set(VALID_TRANSITIONS.keys())

    def test_phases_in_correct_order(self) -> None:
        """Phases should start with created and end with paused."""
        assert PHASES[0] == "created"
        assert PHASES[-1] == "paused"

    def test_all_phases_have_transitions(self) -> None:
        for phase in PHASES:
            assert phase in VALID_TRANSITIONS


class TestProviders:
    """Tests for PROVIDERS registry."""

    def test_has_all_expected_providers(self) -> None:
        expected = {"openai", "anthropic", "gemini", "openrouter", "ollama", "azure"}
        assert set(PROVIDERS.keys()) == expected

    def test_each_provider_has_name(self) -> None:
        for pid, info in PROVIDERS.items():
            assert "name" in info
            assert isinstance(info["name"], str)

    def test_each_provider_has_api_url(self) -> None:
        for pid, info in PROVIDERS.items():
            assert "api_url" in info
            assert isinstance(info["api_url"], str)

    def test_each_provider_has_env_key(self) -> None:
        for pid, info in PROVIDERS.items():
            assert "env_key" in info
            assert isinstance(info["env_key"], str)

    def test_each_provider_has_models(self) -> None:
        for pid, info in PROVIDERS.items():
            assert "models" in info
            assert isinstance(info["models"], list)
            assert len(info["models"]) > 0

    def test_openai_has_gpt_models(self) -> None:
        models = PROVIDERS["openai"]["models"]
        assert any("gpt" in m for m in models)

    def test_ollama_has_local_models(self) -> None:
        models = PROVIDERS["ollama"]["models"]
        assert any(m for m in models)  # non-empty


class TestDefaultFeatures:
    """Tests for DEFAULT_FEATURES."""

    def test_is_dict(self) -> None:
        assert isinstance(DEFAULT_FEATURES, dict)

    def test_all_values_are_bool(self) -> None:
        for value in DEFAULT_FEATURES.values():
            assert isinstance(value, bool)

    def test_some_enabled_some_disabled(self) -> None:
        enabled = [k for k, v in DEFAULT_FEATURES.items() if v]
        disabled = [k for k, v in DEFAULT_FEATURES.items() if not v]
        assert len(enabled) > 0
        assert len(disabled) > 0

    def test_planner_enabled(self) -> None:
        assert DEFAULT_FEATURES.get("planner") is True

    def test_swarm_disabled(self) -> None:
        assert DEFAULT_FEATURES.get("swarm") is False
