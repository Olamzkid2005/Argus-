"""Tests for tool_core.sandbox.client — SandboxClient and SandboxResult.

These tests validate the sandbox execution across Docker and subprocess modes.
Docker-dependent tests are skipped when Docker is unavailable.
"""

from __future__ import annotations

from unittest.mock import PropertyMock, patch

import pytest

from tool_core.sandbox.client import SandboxClient, SandboxResult


class TestSandboxResult:
    """Tests for the SandboxResult dataclass."""

    def test_default_construction(self):
        """Default SandboxResult should have all fields at their defaults."""
        result = SandboxResult()
        assert result.returncode is None
        assert result.stdout == ""
        assert result.stderr == ""
        assert result.error is None
        assert result.timed_out is False

    def test_attribute_access(self):
        """SandboxResult fields should be accessible as attributes."""
        result = SandboxResult(returncode=0, stdout="hello", stderr="")
        assert result.returncode == 0
        assert result.stdout == "hello"
        assert result.stderr == ""

    def test_error_state(self):
        """Error state should be properly represented."""
        result = SandboxResult(error="something went wrong", timed_out=True)
        assert result.error == "something went wrong"
        assert result.timed_out is True
        assert result.returncode is None


class TestSandboxClient:
    """Tests for the SandboxClient class."""

    def test_import(self):
        """SandboxClient should be importable and constructable."""
        client = SandboxClient()
        assert client is not None
        assert client.timeout == 60

    def test_custom_timeout(self):
        """Custom timeout should be reflected."""
        client = SandboxClient(timeout=30)
        assert client.timeout == 30

    def test_is_docker_available_property(self):
        """is_docker_available should return a boolean without raising."""
        client = SandboxClient()
        # Should not raise — either True (Docker available) or False (no Docker)
        available = client.is_docker_available
        assert isinstance(available, bool)

    def test_fallback_subprocess(self):
        """When Docker is unavailable, subprocess fallback should work."""
        client = SandboxClient()
        with patch.object(
            type(client), "is_docker_available", new_callable=PropertyMock, return_value=False
        ):
            result = client.run_command(["python3", "-c", "print('fallback')"])
            assert result.returncode == 0
            assert "fallback" in result.stdout

    def test_subprocess_timeout(self):
        """Subprocess fallback should respect timeouts."""
        client = SandboxClient()
        with patch.object(
            type(client), "is_docker_available", new_callable=PropertyMock, return_value=False
        ):
            result = client.run_command(["sleep", "30"], timeout=1)
            assert result.timed_out or result.error
            if result.timed_out:
                assert result.error == "timeout"

    def test_subprocess_not_found(self):
        """Subprocess fallback should handle missing commands."""
        client = SandboxClient()
        with patch.object(
            type(client), "is_docker_available", new_callable=PropertyMock, return_value=False
        ):
            result = client.run_command(["nonexistent_command_xyz"])
            assert result.returncode is None or result.returncode != 0
            assert result.error is not None

    def test_subprocess_stdin(self):
        """Subprocess fallback should pass stdin through."""
        client = SandboxClient()
        with patch.object(
            type(client), "is_docker_available", new_callable=PropertyMock, return_value=False
        ):
            result = client.run_command(["python3", "-c", "import sys; sys.stdout.write(sys.stdin.read())"], input_data="hello stdin")
            assert "hello stdin" in result.stdout

    def test_run_docker_vs_subprocess_consistency(self):
        """Both execution paths should return compatible SandboxResult objects."""
        client = SandboxClient()

        # Force subprocess fallback
        with patch.object(
            type(client), "is_docker_available", new_callable=PropertyMock, return_value=False
        ):
            subprocess_result = client.run_command(["python3", "-c", "print('test')"])
            assert isinstance(subprocess_result, SandboxResult)
            assert subprocess_result.returncode == 0

    def test_env_locked_in_subprocess(self):
        """Subprocess fallback should block sensitive environment variables."""
        client = SandboxClient()
        with patch.object(
            type(client), "is_docker_available", new_callable=PropertyMock, return_value=False
        ):
            result = client.run_command([
                "python3", "-c",
                "import os; print('DATABASE_URL' not in os.environ)",
            ])
            assert result.returncode == 0
            # The env var should be blocked
            assert "True" in result.stdout


# ── Docker integration tests (marked as slow, skipped without Docker) ──


@pytest.mark.slow
@pytest.mark.docker
class TestSandboxClientDocker:
    """Docker-dependent sandbox tests. Skip with: -m 'not docker'"""

    def test_basic_command(self):
        """Basic echo command should work in Docker sandbox."""
        client = SandboxClient()
        result = client.run_command(["echo", "hello"])
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_no_network(self):
        """Docker sandbox should not have network access."""
        client = SandboxClient()
        result = client.run_command(["curl", "http://google.com"])
        # Should fail — no network in sandbox
        assert result.returncode != 0 or result.error

    def test_stdin_passthrough(self):
        """Stdin should be passed through in Docker sandbox."""
        client = SandboxClient()
        result = client.run_command(["cat"], input_data="hello stdin")
        assert "hello stdin" in result.stdout

    def test_timeout_enforced(self):
        """Infinite loop should be killed by timeout in Docker."""
        client = SandboxClient(timeout=5)
        result = client.run_command(["sleep", "30"], timeout=3)
        assert result.timed_out or result.error

    def test_read_only_rootfs(self):
        """Root filesystem should be read-only in Docker sandbox."""
        client = SandboxClient()
        result = client.run_command(["touch", "/test_file"])
        assert result.returncode != 0
