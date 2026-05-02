"""
Tests for Tool Runner
"""

import tempfile
from pathlib import Path

import pytest

from tools.tool_runner import SecurityException, ToolRunner


class TestToolRunner:
    """Test suite for ToolRunner"""

    def setup_method(self):
        """Setup test fixtures"""
        self.sandbox_dir = tempfile.mkdtemp(prefix="test_sandbox_")
        self.runner = ToolRunner(sandbox_dir=self.sandbox_dir)

    def teardown_method(self):
        """Cleanup after tests"""
        self.runner.cleanup()

    def test_is_dangerous_detects_rm_rf(self):
        """Test that dangerous rm -rf pattern is detected"""
        assert self.runner.is_dangerous("rm", ["-rf", "/"])
        assert self.runner.is_dangerous("rm", ["-fr", "/tmp"])

    def test_is_dangerous_detects_drop_table(self):
        """Test that SQL DROP TABLE is detected"""
        assert self.runner.is_dangerous("psql", ["-c", "DROP TABLE users"])

    def test_is_dangerous_allows_safe_commands(self):
        """Test that safe commands are allowed"""
        assert not self.runner.is_dangerous("echo", ["hello"])
        assert not self.runner.is_dangerous("ls", ["-la"])

    def test_run_blocks_dangerous_commands(self):
        """Test that dangerous commands are blocked"""
        with pytest.raises(SecurityException):
            self.runner.run("rm", ["-rf", "/"])

    def test_run_executes_safe_command(self):
        """Test that safe commands execute successfully"""
        result = self.runner.run("echo", ["test"])

        assert result.success is True
        assert "test" in result.stdout
        assert result.returncode == 0

    def test_run_captures_stderr(self):
        """Test that stderr is captured"""
        result = self.runner.run("ls", ["/nonexistent"])

        assert result.success is False
        assert result.returncode != 0
        assert len(result.stderr) > 0

    def test_run_enforces_timeout(self):
        """Test that timeout is enforced"""
        result = self.runner.run("sleep", ["10"], timeout=1)

        assert result.success is False
        assert result.timeout is True
        assert "timed out" in result.stderr.lower()

    def test_locked_env_has_minimal_variables(self):
        """Test that locked environment has minimal variables"""
        env = self.runner._locked_env()

        assert "PATH" in env
        assert "HOME" in env
        assert "TMPDIR" in env
        # Should not have dangerous variables
        assert "LD_PRELOAD" not in env

    def test_sandbox_directory_exists(self):
        """Test that sandbox directory is created"""
        assert Path(self.sandbox_dir).exists()
        assert Path(self.sandbox_dir).is_dir()
