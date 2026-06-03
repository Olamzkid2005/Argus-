"""
End-to-end tests for the Argus CLI.

Tests the actual CLI entry point, interactive command registry,
security runner (deterministic mode), and provider resolution —
all without requiring external services (PostgreSQL, Redis, workers).

Run with:
    cd argus-cli && python -m pytest tests/test_cli_e2e.py -v --tb=short
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from click.testing import CliRunner

from argus_cli import __app_name__, __version__
from argus_cli.commands.registry import CommandRegistry, execute_command
from argus_cli.config.settings import Config
from argus_cli.core.constants import (
    DEFAULT_FEATURES,
    PROVIDERS,
    VALID_TRANSITIONS,
)
from argus_cli.core.providers import resolve_provider, get_provider_for_model
from argus_cli.core.runner import SecurityRunner
from argus_cli.main import main


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def cli_runner() -> CliRunner:
    """Fixture for Click's CliRunner isolated filesystem."""
    return CliRunner()


@pytest.fixture
def test_config(tmp_path: Path) -> Config:
    """Create a minimal Config for testing (no file I/O to real directories)."""
    cfg = Config()
    cfg.provider = "openai"
    cfg.model = "gpt-4o-mini"
    cfg.api_key = None  # deterministic mode
    cfg.verbose = False
    cfg.stream_output = False
    # Redirect to temp paths so tests never write to real user config/sessions
    cfg.config_dir = tmp_path
    cfg.config_file = tmp_path / "config.toml"
    cfg.sessions_db = tmp_path / "sessions.db"
    return cfg


@pytest.fixture
def registry(test_config: Config) -> CommandRegistry:
    """Create a CommandRegistry with a test config."""
    return CommandRegistry(test_config)


@pytest.fixture
def runner(test_config: Config) -> SecurityRunner:
    """Create a SecurityRunner with a test config."""
    return SecurityRunner(test_config)


@pytest.fixture(autouse=True)
def _mock_orchestrator() -> None:
    """
    Prevent SecurityRunner from connecting to a real Orchestrator/Redis.

    When argus-workers is on the Python path, _get_orchestrator()
    successfully imports the Orchestrator, which then tries to connect
    to Redis (localhost:6379) and fails. This fixture forces the
    deterministic fallback path so tests work without external services.

    Uses unittest.mock.patch.object which is more reliable than
    monkeypatch.setattr for class method patching.
    """
    with patch.object(SecurityRunner, "_get_orchestrator", return_value=None):
        yield


# ═══════════════════════════════════════════════════════════════
# 1. Click CLI Entry Point
# ═══════════════════════════════════════════════════════════════


class TestCliEntry:
    """Tests for the Click CLI entry point (main function)."""

    def test_help_flag(self, cli_runner: CliRunner) -> None:
        """--help should display usage information and exit with code 0."""
        result = cli_runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "ARGUS" in result.output or "Argus" in result.output
        assert "--help" in result.output
        assert "--version" in result.output
        assert "--target" in result.output or "-t" in result.output
        assert "--model" in result.output
        assert "--no-tui" in result.output

    def test_version_flag(self, cli_runner: CliRunner) -> None:
        """--version should print version and exit with code 0."""
        result = cli_runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output
        assert __app_name__.lower() in result.output.lower()

    @patch("argus_cli.main.Config.load")
    def test_config_flag(self, mock_load, cli_runner: CliRunner) -> None:
        """--config should print config paths and exit with code 0."""
        mock_config = MagicMock(spec=Config)
        mock_config.config_dir = Path("/fake/argus/config")
        mock_config.config_file = Path("/fake/argus/config.toml")
        mock_config.sessions_db = Path("/fake/argus/sessions.db")
        mock_load.return_value = mock_config

        result = cli_runner.invoke(main, ["--config"])
        assert result.exit_code == 0
        assert "Config directory" in result.output
        assert "Config file" in result.output
        assert "Sessions DB" in result.output

    def test_providers_flag(self, cli_runner: CliRunner) -> None:
        """--providers should list providers and exit with code 0."""
        result = cli_runner.invoke(main, ["--providers"])
        assert result.exit_code == 0
        assert "Available Model Providers" in result.output or "Provider" in result.output

    def test_unknown_flag_shows_help(self, cli_runner: CliRunner) -> None:
        """An unknown flag should show error and help."""
        result = cli_runner.invoke(main, ["--bogus"])
        assert result.exit_code != 0
        assert "Error" in result.output or "No such option" in result.output


# ═══════════════════════════════════════════════════════════════
# 2. CommandRegistry — Interactive Commands
# ═══════════════════════════════════════════════════════════════


class TestCommandRegistry:
    """Tests for interactive slash commands via CommandRegistry."""

    def test_help_command(self, registry: CommandRegistry) -> None:
        """/help should display the command table."""
        result = registry.execute("/help")
        assert result is not None
        assert "message" in result

    def test_scan_command_no_target(self, registry: CommandRegistry) -> None:
        """/scan without target should return error."""
        result = registry.execute("/scan")
        assert result is not None
        assert "error" in result
        assert "Missing target" in result["error"]

    def test_scan_command_with_target(self, registry: CommandRegistry) -> None:
        """/scan with target should initiate a scan (deterministic mode)."""
        result = registry.execute("/scan example.com")
        assert result is not None
        assert "engagement_id" in result
        assert result["target"] == "example.com"
        assert "phases_completed" in result

    def test_recon_command(self, registry: CommandRegistry) -> None:
        """/recon should run reconnaissance on the target."""
        result = registry.execute("/recon test.com")
        assert result is not None
        assert result.get("target") == "test.com"
        assert result.get("mode") == "deterministic"

    def test_recon_command_no_target(self, registry: CommandRegistry) -> None:
        """/recon without target should return error."""
        result = registry.execute("/recon")
        assert result is not None
        assert "error" in result

    def test_auth_command(self, registry: CommandRegistry) -> None:
        """/auth should run auth testing."""
        result = registry.execute("/auth example.com")
        assert result is not None
        assert "target" in result

    def test_api_command(self, registry: CommandRegistry) -> None:
        """/api should run API security testing."""
        result = registry.execute("/api api.example.com")
        assert result is not None
        assert "target" in result

    def test_report_command(self, registry: CommandRegistry) -> None:
        """/report should generate a report."""
        result = registry.execute("/report")
        assert result is not None

    def test_status_command(self, registry: CommandRegistry) -> None:
        """/status should show engagement status."""
        # First run a scan to set up engagement
        registry.execute("/scan status-test.com")
        result = registry.execute("/status")
        assert result is not None
        assert "engagement_id" in result
        assert "phase" in result

    def test_model_command_change(self, registry: CommandRegistry) -> None:
        """/model should change the active model."""
        result = registry.execute("/model claude-sonnet")
        assert result is not None
        assert result.get("model") == "claude-sonnet"
        assert result.get("provider") == "anthropic"

    def test_model_command_show_current(self, registry: CommandRegistry) -> None:
        """/model without args should show current model."""
        result = registry.execute("/model")
        assert result is not None
        assert "model" in result

    def test_config_command_show(self, registry: CommandRegistry) -> None:
        """/config without args should show configuration."""
        result = registry.execute("/config")
        assert result is not None
        assert "model" in result

    def test_quit_command(self, registry: CommandRegistry) -> None:
        """/quit should return quit action."""
        result = registry.execute("/quit")
        assert result is not None
        assert result.get("action") == "quit"

    def test_exit_command(self, registry: CommandRegistry) -> None:
        """/exit should also return quit action (alias)."""
        result = registry.execute("/exit")
        assert result is not None
        assert result.get("action") == "quit"

    def test_unknown_command(self, registry: CommandRegistry) -> None:
        """Unknown commands should return error."""
        result = registry.execute("/bogus")
        assert result is not None
        assert "error" in result
        assert "Unknown command" in result["error"]

    def test_bare_input_treated_as_scan(self, registry: CommandRegistry) -> None:
        """Bare input (no slash) should be treated as a scan command."""
        result = registry.execute("example.com")
        assert result is not None
        assert "engagement_id" in result
        assert result["target"] == "example.com"

    def test_empty_input_returns_none(self, registry: CommandRegistry) -> None:
        """Empty input should return None."""
        result = registry.execute("")
        assert result is None

    def test_whitespace_input_returns_none(self, registry: CommandRegistry) -> None:
        """Whitespace-only input should return None."""
        result = registry.execute("   ")
        assert result is None


# ═══════════════════════════════════════════════════════════════
# 3. SecurityRunner (Deterministic Mode)
# ═══════════════════════════════════════════════════════════════


class TestSecurityRunner:
    """Tests for SecurityRunner in deterministic mode (no external services)."""

    def test_scan_returns_engagement(self, runner: SecurityRunner) -> None:
        """scan() should return scan results with engagement_id."""
        result = runner.scan("example.com")
        assert "engagement_id" in result
        assert result["target"] == "example.com"
        assert "phases_completed" in result

    def test_recon_returns_results(self, runner: SecurityRunner) -> None:
        """recon() should return recon results."""
        result = runner.recon("example.com")
        assert "mode" in result
        assert result["mode"] == "deterministic"

    def test_auth_test_returns_results(self, runner: SecurityRunner) -> None:
        """auth_test() should return auth testing results."""
        result = runner.auth_test("example.com")
        assert "skipped" in result or "target" in result

    def test_api_test_returns_results(self, runner: SecurityRunner) -> None:
        """api_test() should return API testing results."""
        result = runner.api_test("example.com")
        assert "skipped" in result or "target" in result

    def test_report_returns_results(self, runner: SecurityRunner) -> None:
        """report() should return report results."""
        result = runner.report()
        assert result is not None

    def test_get_status(self, runner: SecurityRunner) -> None:
        """get_status() should return current state."""
        status = runner.get_status()
        assert "engagement_id" in status
        assert "phase" in status
        assert "model" in status
        assert "provider" in status

    def test_stop_sets_paused(self, runner: SecurityRunner) -> None:
        """stop() should set phase to paused."""
        runner.scan("example.com")
        runner.stop()
        status = runner.get_status()
        assert status["phase"] == "paused"

    def test_deterministic_phase_fallback(self, runner: SecurityRunner) -> None:
        """_run_phase should fall back to deterministic mode when orchestrator is None."""
        result = runner._run_phase_deterministic("recon", {"target": "test.com"})
        assert result["mode"] == "deterministic"
        assert result["target"] == "test.com"
        assert "tools" in result

    def test_multiple_scans_create_new_engagement(self, runner: SecurityRunner) -> None:
        """Each scan on a fresh runner creates a new engagement_id."""
        runner2 = SecurityRunner(runner.config)
        result1 = runner.scan("target1.com")
        result2 = runner2.scan("target2.com")
        assert result1["engagement_id"] != result2["engagement_id"]
        assert result1["target"] == "target1.com"
        assert result2["target"] == "target2.com"


# ═══════════════════════════════════════════════════════════════
# 4. Convenience execute_command Function
# ═══════════════════════════════════════════════════════════════


class TestExecuteCommand:
    """Tests for the execute_command convenience function."""

    def test_execute_scan(self, test_config: Config) -> None:
        """execute_command should run a scan command."""
        result = execute_command("/scan test.com", test_config)
        assert result is not None
        assert result.get("target") == "test.com"

    def test_execute_help(self, test_config: Config) -> None:
        """execute_command should run a help command."""
        result = execute_command("/help", test_config)
        assert result is not None

    def test_execute_unknown(self, test_config: Config) -> None:
        """execute_command should handle unknown commands."""
        result = execute_command("/unknown_cmd", test_config)
        assert result is not None
        assert "error" in result


# ═══════════════════════════════════════════════════════════════
# 5. Provider Resolution
# ═══════════════════════════════════════════════════════════════


class TestProviderResolution:
    """Tests for provider resolution logic."""

    def test_openai_gpt(self) -> None:
        """gpt-* models should resolve to OpenAI."""
        provider, model = resolve_provider("gpt-5")
        assert provider == "openai"
        assert model == "gpt-5"

    def test_anthropic_claude(self) -> None:
        """claude-* models should resolve to Anthropic."""
        provider, model = resolve_provider("claude-sonnet-4")
        assert provider == "anthropic"
        assert model == "claude-sonnet-4"

    def test_gemini(self) -> None:
        """gemini-* models should resolve to Google Gemini."""
        provider, model = resolve_provider("gemini-2.5-pro")
        assert provider == "gemini"
        assert model == "gemini-2.5-pro"

    def test_ollama_explicit(self) -> None:
        """ollama:model syntax should resolve to Ollama."""
        provider, model = resolve_provider("ollama:qwen3")
        assert provider == "ollama"
        assert model == "qwen3"

    def test_ollama_shorthand_qwen(self) -> None:
        """qwen models should resolve to Ollama."""
        provider, model = resolve_provider("qwen3")
        assert provider == "ollama"
        assert model == "qwen3"

    def test_ollama_shorthand_llama(self) -> None:
        """llama models should resolve to Ollama."""
        provider, model = resolve_provider("llama3.3")
        assert provider == "ollama"
        assert model == "llama3.3"

    def test_unknown_fallback(self) -> None:
        """Unknown model shorthand should fall back to OpenAI."""
        provider, model = resolve_provider("unknown-model-xyz")
        assert provider == "openai"
        assert model == "unknown-model-xyz"

    def test_provider_config_from_env(self) -> None:
        """get_provider_for_model should return a ProviderConfig."""
        with patch.dict("os.environ", {}, clear=True):
            config = get_provider_for_model("gpt-4o")
            assert config.id == "openai"
            assert config.default_model == "gpt-4o"

    def test_providers_are_configured(self) -> None:
        """All expected providers should be registered."""
        expected = {"openai", "anthropic", "gemini", "openrouter", "ollama", "azure"}
        assert set(PROVIDERS.keys()) == expected


# ═══════════════════════════════════════════════════════════════
# 6. Configuration
# ═══════════════════════════════════════════════════════════════


class TestConfiguration:
    """Tests for Config behavior."""

    def test_default_values(self) -> None:
        """Config should have sensible defaults."""
        cfg = Config()
        assert cfg.provider == "openai"
        assert cfg.model == "gpt-4o-mini"
        assert cfg.temperature == 0.3
        assert cfg.aggressiveness == "balanced"
        assert cfg.output_format == "markdown"

    def test_feature_flags_defaults(self) -> None:
        """Default feature flags should include planner, recon, auth, api_testing, reporting."""
        cfg = Config()
        assert cfg.is_enabled("planner") is True
        assert cfg.is_enabled("recon") is True
        assert cfg.is_enabled("auth") is True
        assert cfg.is_enabled("api_testing") is True
        assert cfg.is_enabled("reporting") is True

    def test_feature_flags_disabled(self) -> None:
        """Some feature flags should be disabled by default."""
        cfg = Config()
        assert cfg.is_enabled("swarm") is False
        assert cfg.is_enabled("chain_exploits") is False

    def test_to_dict_masks_api_key(self) -> None:
        """to_dict() should mask the API key."""
        cfg = Config()
        cfg.api_key = "sk-test-key-12345"
        d = cfg.to_dict()
        assert "..." in d["api_key"]
        assert "sk-test" in d["api_key"]

    def test_is_enabled_unknown_flag(self) -> None:
        """is_enabled for unknown flag should return False."""
        cfg = Config()
        assert cfg.is_enabled("nonexistent_flag") is False

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        """Config should roundtrip through save and load."""
        config_file = tmp_path / "config.toml"
        cfg_original = Config()
        cfg_original.provider = "anthropic"
        cfg_original.model = "claude-sonnet-4"
        cfg_original.temperature = 0.7
        cfg_original.config_file = config_file
        cfg_original.config_dir = tmp_path
        cfg_original.sessions_db = tmp_path / "sessions.db"
        cfg_original.save()

        assert config_file.exists()

        cfg_loaded = Config.load(config_file)
        assert cfg_loaded.provider == "anthropic"
        assert cfg_loaded.model == "claude-sonnet-4"
        assert cfg_loaded.temperature == 0.7

    def test_env_override(self) -> None:
        """Environment variables should override config defaults."""
        with patch.dict("os.environ", {"ARGUS_MODEL": "gemini-2.5-pro", "ARGUS_TEMPERATURE": "0.9"}, clear=True):
            from argus_cli.config.settings import Config
            # Config.load uses os.environ._apply_env
            cfg = Config()
            cfg._apply_env()
            assert cfg.model == "gemini-2.5-pro"
            assert cfg.temperature == 0.9


# ═══════════════════════════════════════════════════════════════
# 7. Constants Validation
# ═══════════════════════════════════════════════════════════════


class TestConstants:
    """Validate core constants and invariants."""

    def test_valid_transitions_symmetry(self) -> None:
        """All states should appear as keys in VALID_TRANSITIONS."""
        all_states = {
            "created",
            "recon",
            "scanning",
            "analyzing",
            "reporting",
            "complete",
            "failed",
            "paused",
        }
        assert set(VALID_TRANSITIONS.keys()) == all_states

    def test_no_cycle_from_terminal_states(self) -> None:
        """Terminal states (complete, failed) must have no transitions out."""
        assert VALID_TRANSITIONS["complete"] == []
        assert VALID_TRANSITIONS["failed"] == []

    def test_default_features_structure(self) -> None:
        """DEFAULT_FEATURES should be a dict of str -> bool."""
        assert isinstance(DEFAULT_FEATURES, dict)
        for key, value in DEFAULT_FEATURES.items():
            assert isinstance(key, str)
            assert isinstance(value, bool)


# ═══════════════════════════════════════════════════════════════
# 8. Command Registry Edge Cases
# ═══════════════════════════════════════════════════════════════


class TestCommandEdgeCases:
    """Edge cases for command handling."""

    def test_scan_with_special_chars_target(self, registry: CommandRegistry) -> None:
        """Scan target with special characters should not crash."""
        result = registry.execute("/scan https://example.com/path?q=test&x=1")
        assert result is not None
        assert "engagement_id" in result

    def test_model_with_ollama_prefix(self, registry: CommandRegistry) -> None:
        """/model with ollama: prefix should work."""
        result = registry.execute("/model ollama:deepseek-r1")
        assert result is not None
        assert result.get("model") == "deepseek-r1"
        assert result.get("provider") == "ollama"

    def test_config_set_value(self, registry: CommandRegistry) -> None:
        """/config with key=value should update the setting."""
        result = registry.execute("/config temperature=0.5")
        assert result is not None
        assert result.get("status") == "updated"
        assert registry.config.temperature == 0.5

    def test_config_set_unknown_key(self, registry: CommandRegistry) -> None:
        """/config with unknown key should return error."""
        result = registry.execute("/config nonexistent_key=1")
        assert result is not None
        assert "error" in result

    def test_sessions_empty(self, registry: CommandRegistry) -> None:
        """/sessions without prior sessions should return empty list."""
        result = registry.execute("/sessions")
        assert result is not None
        assert "sessions" in result
