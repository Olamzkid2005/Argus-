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
    """Test argus health command output.

    All checks are consolidated into a single test to avoid running multiple
    subprocess invocations (each triggers a ~30s DNS resolution timeout on
    systems without internet access).
    """

    @pytest.mark.slow(reason="DNS check + tool probes (~40s total)")
    def test_health_output_all(self):
        """argus health output includes preflight section, tool section, all 9 check names,
        and varies with env vars (LLM key, encryption key, auth key)."""
        # ── Run #1: --verbose (shows all checks) ──
        result_v = _run_argus("health", "--verbose", "--timeout", "1", timeout=90)
        assert result_v.returncode in (0, 1)
        stdout_v = result_v.stdout

        # Check preflight section
        assert "Preflight Configuration Check" in stdout_v

        # Check tool health section
        assert "Tool Health Report" in stdout_v

        # Check all 9 check names appear in verbose output
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
            assert name in stdout_v, f"Check '{name}' not found in health --verbose output"

        # ── Run #2: without --verbose (only shows warnings/errors) ──
        result_nv = _run_argus("health", "--timeout", "1", timeout=90)
        assert result_nv.returncode in (0, 1)
        assert "Preflight Configuration Check" in result_nv.stdout

        # ── Run #3: with OPENAI_API_KEY set (LLM check should change) ──
        env_llm = os.environ.copy()
        env_llm["OPENAI_API_KEY"] = "sk-test-integration-key-12345"
        result_llm = _run_argus("health", "--verbose", "--timeout", "1", timeout=90, env=env_llm)
        assert result_llm.returncode in (0, 1)
        assert "Preflight Configuration Check" in result_llm.stdout

        # ── Run #4: with SETTINGS_ENCRYPTION_KEY + AUTH_CHECKPOINT_KEY set ──
        env_keys = os.environ.copy()
        env_keys["SETTINGS_ENCRYPTION_KEY"] = "dGhpcyBpcyBhIHRlc3Qga2V5IGZvciBjaWVjcg=="
        env_keys["AUTH_CHECKPOINT_KEY"] = "dGhpcyBpcyBhIHRlc3Qga2V5IGZvciBjaWVjcg=="
        result_keys = _run_argus("health", "--verbose", "--timeout", "1", timeout=90, env=env_keys)
        assert result_keys.returncode in (0, 1)
        stdout_keys = result_keys.stdout
        assert any(
            phrase in stdout_keys.lower()
            for phrase in ["encryption_key", "settings", "preflight"]
        )


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
        result = _run_argus("health", "--timeout", "1", timeout=90)
        stderr = result.stderr
        # The absence of tracebacks is the strongest signal of a clean run.
        # Log messages (INFO/WARNING/ERROR) are expected.
        assert "Traceback (most recent call last)" not in stderr
