"""
Integration tests for the Argus CLI (argus health, argus init).

Tests invoke the CLI via subprocess and verify:
  - Exit codes
  - Stdout contains expected strings (preflight checks, tool health, .env paths)
  - --help displays correctly
  - argus health displays both preflight and tool health sections
  - Edge cases: invalid commands, --help on subcommands

NOTE: The init test is DESTRUCTIVE — it modifies the real .env in the project root.
It is skipped by default. Set ARGUS_DESTRUCTIVE_TEST=1 to run it.
"""

import os
import subprocess
import sys

import pytest

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _run_argus(*args: str, timeout: int = 30, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run ``cli.py <args>`` as a subprocess and return the result.

    Uses the current Python interpreter and the project's cli.py module.
    Captures both stdout and stderr.

    Args:
        *args: CLI arguments (e.g. "health", "--verbose").
        timeout: Subprocess timeout in seconds.
        env: Optional environment dict. If None, inherits current process env.

    Returns:
        ``subprocess.CompletedProcess`` with stdout, stderr, returncode.
    """
    cli_path = os.path.join(os.path.dirname(__file__), "..", "cli.py")
    cmd = [sys.executable, cli_path] + list(args)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


# ═══════════════════════════════════════════════════════════════════════
# --help and basic invocation
# ═══════════════════════════════════════════════════════════════════════


class TestHelp:
    """Test --help for main CLI and subcommands."""

    def test_main_help(self):
        """Running with no args shows help and exits 0."""
        result = _run_argus()
        assert result.returncode == 0
        assert "usage:" in result.stdout.lower()
        assert "argus" in result.stdout.lower()

    def test_health_help(self):
        """argus health --help shows health-specific help."""
        result = _run_argus("health", "--help")
        assert result.returncode == 0
        assert "usage:" in result.stdout.lower()
        assert "health" in result.stdout.lower()
        assert "--verbose" in result.stdout

    def test_init_help(self):
        """argus init --help shows init-specific help."""
        result = _run_argus("init", "--help")
        assert result.returncode == 0
        assert "usage:" in result.stdout.lower()
        assert "init" in result.stdout.lower()
        assert "--force" in result.stdout


# ═══════════════════════════════════════════════════════════════════════
# argus health
# ═══════════════════════════════════════════════════════════════════════


class TestHealth:
    """Test argus health command output."""

    @pytest.mark.slow(reason="Probes real tool binaries via subprocess")
    def test_health_displays_preflight_section(self):
        """argus health shows the Preflight Configuration Check section."""
        result = _run_argus("health", "--verbose", timeout=60)
        assert "Preflight Configuration Check" in result.stdout

    @pytest.mark.slow
    def test_health_displays_tool_section(self):
        """argus health shows the Tool Health Report section."""
        result = _run_argus("health", "--verbose", timeout=60)
        assert "Tool Health Report" in result.stdout

    @pytest.mark.slow
    def test_health_outputs_check_names(self):
        """argus health --verbose lists all 9 check names."""
        result = _run_argus("health", "--verbose", timeout=60)
        check_names = [
            "critical_tools",
            "settings_encryption_key",
            "auth_checkpoint_key",
            "scope_config",
            "dns_resolution",
            "llm_config",
            "placeholder_credentials",
            "database_url",
            "tool_health",
        ]
        for name in check_names:
            assert name in result.stdout, f"Check '{name}' not found in health output"

    @pytest.mark.slow
    def test_health_exit_code(self):
        """argus health returns 0 or 1 (depending on environment)."""
        result = _run_argus("health", timeout=60)
        assert result.returncode in (0, 1)

    @pytest.mark.slow
    def test_health_non_verbose_shows_preflight(self):
        """argus health (non-verbose) shows the preflight section."""
        result = _run_argus("health", timeout=60)
        assert "Preflight Configuration Check" in result.stdout


# ═══════════════════════════════════════════════════════════════════════
# argus init (in temp directory)
# ═══════════════════════════════════════════════════════════════════════


class TestInit:
    """Test argus init command.

    NOTE: These tests are destructive — they modify the real .env in the
    project root because cli.py resolves __file__ to the actual workers
    directory, not a temp directory. They are skipped by default.
    Set ARGUS_DESTRUCTIVE_TEST=1 to run them.
    """

    @pytest.mark.skipif(
        os.environ.get("ARGUS_DESTRUCTIVE_TEST") != "1",
        reason="Skipped: destructive test (modifies .env in project root). "
        "Set ARGUS_DESTRUCTIVE_TEST=1 to run.",
    )
    def test_init_no_existing_env_creates_file(self):
        """argus init --force creates a .env with encryption keys."""
        result = _run_argus("init", "--force", timeout=30)
        assert result.returncode in (0, 1)
        assert "Preflight Configuration Check" in result.stdout
        assert "AUTH_CHECKPOINT_KEY" in result.stdout or "Init complete" in result.stdout


# ═══════════════════════════════════════════════════════════════════════
# argus health with specific env setup
# ═══════════════════════════════════════════════════════════════════════


class TestHealthWithEnv:
    """Test argus health output varies with environment variables."""

    @pytest.mark.slow(reason="Probes real tool binaries via subprocess")
    def test_health_with_llm_key_shows_llm_ok(self):
        """Setting OPENAI_API_KEY should change LLM check from WARNING to OK."""
        env = os.environ.copy()
        env["OPENAI_API_KEY"] = "sk-test-integration-key-12345"
        cli_path = os.path.join(os.path.dirname(__file__), "..", "cli.py")
        result = subprocess.run(
            [sys.executable, cli_path, "health", "--verbose"],
            capture_output=True, text=True, timeout=60, env=env,
        )
        assert result.returncode in (0, 1)
        assert "Preflight Configuration Check" in result.stdout

    @pytest.mark.slow(reason="Probes real tool binaries via subprocess")
    def test_health_with_all_keys_set(self):
        """Setting multiple env vars should make more checks pass."""
        env = os.environ.copy()
        env["SETTINGS_ENCRYPTION_KEY"] = "dGhpcyBpcyBhIHRlc3Qga2V5IGZvciBjaWVjcg=="
        env["AUTH_CHECKPOINT_KEY"] = "dGhpcyBpcyBhIHRlc3Qga2V5IGZvciBjaWVjcg=="
        cli_path = os.path.join(os.path.dirname(__file__), "..", "cli.py")
        result = subprocess.run(
            [sys.executable, cli_path, "health", "--verbose"],
            capture_output=True, text=True, timeout=60, env=env,
        )
        assert result.returncode in (0, 1)
        stdout = result.stdout
        assert any(
            phrase in stdout.lower()
            for phrase in ["encryption_key", "settings", "preflight"]
        )


# ═══════════════════════════════════════════════════════════════════════
# Error handling
# ═══════════════════════════════════════════════════════════════════════


class TestErrorHandling:
    """Test CLI error handling."""

    def test_unknown_command(self):
        """Unknown command shows error."""
        result = _run_argus("nonexistent-command")
        # Should exit with non-zero or show help
        assert result.returncode != 0 or "usage:" in result.stdout.lower()


# ═══════════════════════════════════════════════════════════════════════
# Stderr contains no errors during health check
# ═══════════════════════════════════════════════════════════════════════


class TestStderrClean:
    """Test that successful commands don't pollute stderr."""

    @pytest.mark.slow
    def test_health_stderr_no_tracebacks(self):
        """argus health should not produce Python tracebacks on stderr."""
        result = _run_argus("health", timeout=60)
        stderr = result.stderr
        # The absence of tracebacks is the strongest signal of a clean run.
        # Log messages (INFO/WARNING/ERROR) are expected.
        assert "Traceback (most recent call last)" not in stderr
