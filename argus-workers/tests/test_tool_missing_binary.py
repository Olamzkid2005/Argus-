"""Tests for ToolRunner fail-loud behavior on missing tool binaries.

Previously a missing binary surfaced as a confusing FileNotFoundError →
generic EXCEPTION status. Now it must return a NOT_INSTALLED result with an
install hint so the agent/operator see the real cause.
"""

import sys
import tempfile

import pytest

from cache import CacheMode
from tool_core.result import ToolStatus
from tools.tool_runner import ToolRunner

_windows_skip = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="Test uses POSIX-style path resolution semantics",
)


@_windows_skip
class TestMissingBinary:
    def setup_method(self):
        self.sandbox_dir = tempfile.mkdtemp(prefix="test_missing_bin_")
        self.runner = ToolRunner(sandbox_dir=self.sandbox_dir)

    def teardown_method(self):
        self.runner.cleanup()

    def test_missing_binary_returns_not_installed(self):
        result = self.runner.run(
            "argus_tool_that_does_not_exist_xyz",
            ["--version"],
            cache_mode=CacheMode.NO_CACHE,
        )
        assert result.status == ToolStatus.NOT_INSTALLED
        assert result.success is False

    def test_not_installed_result_carries_install_hint(self):
        result = self.runner.run(
            "argus_tool_that_does_not_exist_xyz",
            ["--version"],
            cache_mode=CacheMode.NO_CACHE,
        )
        assert "install" in (result.fix_hint or "").lower()

    def test_missing_binary_result_is_terminal(self):
        """A NOT_INSTALLED outcome is a finished result, not partial state."""
        result = self.runner.run(
            "argus_tool_that_does_not_exist_xyz",
            ["--version"],
            cache_mode=CacheMode.NO_CACHE,
        )
        assert result.finished_at is not None

    def test_installed_binary_still_runs(self):
        """Guard: real binaries on PATH are unaffected by the fail-loud check."""
        result = self.runner.run("echo", ["still-works"], cache_mode=CacheMode.NO_CACHE)
        assert result.status == ToolStatus.SUCCESS
        assert "still-works" in result.stdout
