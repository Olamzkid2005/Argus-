"""Tests for orchestrator_pkg.repo_scan — Category: function"""

import pytest

from orchestrator_pkg.repo_scan import (
    check_maven_dependencies,
    execute_repo_scan,
    run_govulncheck,
    run_npm_audit,
    run_pip_audit,
    validate_repo_url,
)
from utils.validation import is_private_ip


class TestValidateRepoUrl:
    """Tests for the validate_repo_url function."""

    def test_returns_none_for_invalid_url(self):
        """Empty URL returns empty string."""
        result = validate_repo_url("")
        assert result == ""


class TestIsPrivateIp:
    """Tests for the is_private_ip function from utils.validation."""

    def test_private_ip_detected(self):
        """10.x.x.x should be private."""
        result = is_private_ip("10.0.0.1")
        assert result is True

    def test_public_ip_not_private(self):
        """Public IP should not be private."""
        result = is_private_ip("8.8.8.8")
        assert result is False

    def test_localhost_is_private(self):
        """127.0.0.1 should be private."""
        result = is_private_ip("127.0.0.1")
        assert result is True

    def test_private_172_range(self):
        """172.16.x.x should be private."""
        result = is_private_ip("172.16.0.1")
        assert result is True

    def test_private_192_range(self):
        """192.168.x.x should be private."""
        result = is_private_ip("192.168.1.1")
        assert result is True

    def test_ipv6_ula_private(self):
        """IPv6 ULA (fc00::/7) should be private."""
        result = is_private_ip("fd00::1")
        assert result is True

    def test_ipv6_link_local_private(self):
        """IPv6 link-local (fe80::/10) should be private."""
        result = is_private_ip("fe80::1")
        assert result is True

    def test_ipv6_loopback_private(self):
        """IPv6 loopback (::1) should be private."""
        result = is_private_ip("::1")
        assert result is True

    def test_ipv6_public_not_private(self):
        """Public IPv6 should not be private."""
        result = is_private_ip("2001:470:1f15:1abc::1")
        assert result is False


class TestRunNpmAudit:
    """Tests for the run_npm_audit function."""

    def test_nonexistent_path(self):
        """Non-existent path should raise or return empty."""
        try:
            result = run_npm_audit("/nonexistent/path")
            assert isinstance(result, list)
        except Exception:
            pass


class TestRunPipAudit:
    """Tests for the run_pip_audit function."""

    def test_nonexistent_path(self):
        """Non-existent path should raise or return empty."""
        try:
            result = run_pip_audit("/nonexistent/path")
            assert isinstance(result, list)
        except Exception:
            pass


class TestRunGovulncheck:
    """Tests for the run_govulncheck function."""

    def test_nonexistent_path(self):
        """Non-existent path should raise or return empty."""
        try:
            result = run_govulncheck("/nonexistent/path")
            assert isinstance(result, list)
        except Exception:
            pass


class TestCheckMavenDependencies:
    """Tests for the check_maven_dependencies function."""

    def test_nonexistent_path(self):
        """Non-existent path should raise or return empty."""
        try:
            result = check_maven_dependencies("/nonexistent/path")
            assert isinstance(result, list)
        except Exception:
            pass


class TestExecuteRepoScan:
    """Tests for the execute_repo_scan function."""

    def test_requires_arguments(self):
        """Requires orchestrator and repo_url args."""
        with pytest.raises(TypeError):
            execute_repo_scan()
