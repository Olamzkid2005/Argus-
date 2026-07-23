"""
Tests for tool_core/health_checker.py — tool version probing and health checks.

Uses mocked subprocess.run to test probe logic, version parsing,
caching, parallel probing, and display formatting.
"""

from unittest.mock import MagicMock, patch

import pytest

from tool_core.health_checker import (
    ToolHealthChecker,
    HealthReport,
    ToolHealthResult,
    display_health_report,
)


def _make_result(
    name: str = "test-tool",
    binary: str = "test-tool",
    status: str = "unavailable",
    available: bool = False,
    responsive: bool = False,
    version: str = "",
    probe_command: str = "--version",
    error: str = "",
    path: str = "",
) -> ToolHealthResult:
    """Helper to construct ToolHealthResult with fewer required args."""
    return ToolHealthResult(
        name=name,
        binary=binary,
        status=status,
        available=available,
        responsive=responsive,
        version=version,
        probe_command=probe_command,
        error=error,
        path=path,
    )


class TestToolHealthResult:
    """Tests for ToolHealthResult dataclass."""

    def test_creation(self):
        r = _make_result(name="nuclei", status="healthy", version="3.2.0")
        assert r.name == "nuclei"
        assert r.status == "healthy"
        assert r.version == "3.2.0"

    def test_defaults(self):
        r = _make_result(name="ghost")
        assert r.status == "unavailable"
        assert r.available is False


class TestHealthReport:
    """Tests for HealthReport dataclass."""

    @pytest.fixture
    def report(self):
        return HealthReport(
            healthy=[_make_result("tool-a", status="healthy", version="1.0")],
            degraded=[_make_result("tool-b", status="degraded", version="0.5")],
            unavailable=[_make_result("tool-c", status="unavailable")],
        )

    def test_counts(self, report):
        assert report.healthy_count == 1
        assert report.degraded_count == 1
        assert report.unavailable_count == 1
        assert report.total == 3

    def test_empty_counts(self):
        r = HealthReport()
        assert r.total == 0
        assert r.healthy_count == 0
        assert r.degraded_count == 0
        assert r.unavailable_count == 0

    def test_summary_property(self, report):
        s = report.summary
        assert "1 healthy" in s
        assert "1 degraded" in s
        assert "1 unavailable" in s


class TestToolHealthChecker:
    """Test suite for ToolHealthChecker with mocked subprocess."""

    @pytest.fixture
    def checker(self):
        return ToolHealthChecker(probe_timeout=2)

    @pytest.fixture
    def mock_run_healthy(self):
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = "nuclei version 3.2.0\n"
        mock.stderr = ""
        return mock

    def test_probe_healthy_tool(self, checker, mock_run_healthy):
        """Healthy tool with --version returns correct result."""
        with patch.object(checker, "_resolve_binary", return_value="/usr/bin/nuclei"), \
             patch("subprocess.run", return_value=mock_run_healthy):
            result = checker.check("nuclei")

        assert result.status == "healthy"
        assert result.name == "nuclei"
        assert result.version == "3.2.0"
        assert result.available is True
        assert result.responsive is True

    def test_probe_unavailable_tool(self, checker):
        """Tool not on PATH returns unavailable status."""
        with patch.object(checker, "_resolve_binary", return_value=None):
            result = checker.check("nonexistent-tool")

        assert result.status == "unavailable"
        assert result.name == "nonexistent-tool"
        assert result.available is False

    def test_binary_resolution_failure(self, checker):
        """No binary resolved -> unavailable."""
        with patch.object(checker, "_resolve_binary", return_value=None):
            result = checker.check("ghost-tool")
        assert result.status == "unavailable"

    def test_probe_timeout(self, checker):
        """TimeoutExpired returns degraded."""
        with patch.object(checker, "_resolve_binary", return_value="/usr/bin/slow-tool"), \
             patch("subprocess.run", side_effect=__import__("subprocess").TimeoutExpired("cmd", 2)):
            result = checker.check("slow-tool")

        assert result.status == "degraded"
        assert result.available is True

    def test_probe_nonzero_exit(self, checker):
        """Non-zero exit code returns degraded (no version parsed)."""
        mock_run = MagicMock()
        mock_run.returncode = 1
        mock_run.stdout = ""
        mock_run.stderr = "error: unknown flag"

        with patch.object(checker, "_resolve_binary", return_value="/usr/bin/old-tool"), \
             patch("subprocess.run", return_value=mock_run):
            result = checker.check("old-tool")

        assert result.status == "degraded"
        assert result.available is True

    def test_cache_hit(self, checker, mock_run_healthy):
        """Subsequent check returns cached result without re-probing."""
        with patch.object(checker, "_resolve_binary", return_value="/usr/bin/nuclei"), \
             patch("subprocess.run", return_value=mock_run_healthy) as mock_subprocess:

            result1 = checker.check("nuclei")
            assert result1.status == "healthy"
            assert mock_subprocess.call_count == 1

            result2 = checker.check("nuclei")
            assert result2.status == "healthy"
            assert mock_subprocess.call_count == 1  # Cached

    def test_cache_ttl(self, checker, mock_run_healthy):
        """Cache expires after TTL and re-probes."""
        with patch.object(checker, "_resolve_binary", return_value="/usr/bin/nuclei"), \
             patch("subprocess.run", return_value=mock_run_healthy) as mock_subprocess:

            checker.check("nuclei")
            assert mock_subprocess.call_count == 1

            # Force cache expiry
            checker._cache_time = 0

            checker.check("nuclei")
            assert mock_subprocess.call_count == 2

    def test_invalidate_clears_cache(self, checker, mock_run_healthy):
        """invalidate() clears cached result."""
        with patch.object(checker, "_resolve_binary", return_value="/usr/bin/nuclei"), \
             patch("subprocess.run", return_value=mock_run_healthy) as mock_subprocess:

            checker.check("nuclei")
            assert mock_subprocess.call_count == 1

            checker.invalidate("nuclei")
            checker.check("nuclei")
            assert mock_subprocess.call_count == 2

    def test_invalidate_all(self, checker, mock_run_healthy):
        """invalidate() without args clears all cache."""
        with patch.object(checker, "_resolve_binary", return_value="/usr/bin/nuclei"), \
             patch("subprocess.run", return_value=mock_run_healthy) as mock_subprocess:

            checker.check("nuclei")
            checker.check("httpx")  # Different tool

            # First httpx calls get_version_probe which returns "-version" for httpx
            # But the mock doesn't care, it always returns mock_run_healthy
            assert mock_subprocess.call_count == 2

            checker.invalidate()
            checker.check("nuclei")
            assert mock_subprocess.call_count == 3  # Re-probed

    def test_check_all_parallel(self, checker):
        """check_all probes multiple tools in parallel."""
        def mock_check(name):
            return _make_result(name=name, status="healthy" if name in ("a", "b") else "unavailable")

        with patch.object(checker, "check", side_effect=mock_check):
            report = checker.check_all(tool_names=["a", "b", "c"], max_workers=4)

        assert report.total == 3
        assert report.healthy_count == 2
        assert report.unavailable_count == 1

    def test_check_all_empty(self, checker):
        """check_all with empty list returns empty report."""
        report = checker.check_all(tool_names=[])
        assert report.total == 0

    def test_get_all_tool_names_returns_list(self, checker):
        """_get_all_tool_names returns non-empty list."""
        names = checker._get_all_tool_names()
        assert isinstance(names, list)
        assert len(names) > 0
        assert "nuclei" in names

    def test_get_version_returns_string(self, checker):
        """get_version returns version string from cached probe."""
        with patch.object(checker, "_resolve_binary", return_value="/usr/bin/nuclei"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "nuclei version 3.2.0\n"
            mock_run.return_value.stderr = ""

            version = checker.get_version("nuclei")
            assert version == "3.2.0"

    def test_get_version_unavailable(self, checker):
        """get_version returns empty string for unavailable tool."""
        with patch.object(checker, "_resolve_binary", return_value=None):
            version = checker.get_version("nonexistent")
            assert version == ""


class TestDisplayHealthReport:
    """Tests for display_health_report formatting function."""

    @pytest.fixture
    def mixed_report(self):
        return HealthReport(
            healthy=[_make_result("nuclei", status="healthy", version="3.2.0")],
            degraded=[_make_result("old-tool", status="degraded", version="0.5")],
            unavailable=[_make_result("ghost", status="unavailable")],
        )

    def test_non_verbose_hides_healthy(self, mixed_report):
        output = display_health_report(mixed_report, verbose=False)
        assert "UNAVAILABLE" in output.upper() or "unavailable" in output.lower()
        assert "DEGRADED" in output.upper() or "degraded" in output.lower()
        # Non-verbose: healthy tools are hidden
        assert "nuclei" not in output

    def test_verbose_shows_all(self, mixed_report):
        output = display_health_report(mixed_report, verbose=True)
        assert "nuclei" in output
        assert "ghost" in output

    def test_all_healthy(self):
        report = HealthReport(
            healthy=[
                _make_result("nuclei", status="healthy", version="3.2.0"),
                _make_result("httpx", status="healthy", version="1.6.0"),
            ],
        )
        output = display_health_report(report, verbose=False)
        assert "All 2 tools are healthy" in output

    def test_empty_report(self):
        output = display_health_report(HealthReport(), verbose=True)
        assert "0" in output

    def test_summary_in_footer(self, mixed_report):
        output = display_health_report(mixed_report, verbose=False)
        assert "1 healthy" in output
        assert "1 degraded" in output
        assert "1 unavailable" in output
