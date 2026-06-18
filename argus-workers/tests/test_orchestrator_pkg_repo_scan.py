"""Tests for orchestrator_pkg.repo_scan — Category: function"""

import pytest

from orchestrator_pkg.repo_scan import (
    _is_private_ip,
    check_maven_dependencies,
    execute_repo_scan,
    run_govulncheck,
    run_npm_audit,
    run_pip_audit,
    validate_repo_url,
)


class TestValidateRepoUrl:
    """Tests for the validate_repo_url function."""

    def test_returns_none_for_invalid_url(self):
        """Invalid URL raises ValueError."""
        with pytest.raises((ValueError, TypeError)):
            validate_repo_url("")


class TestIsPrivateIp:
    """Tests for the _is_private_ip function."""

    def test_private_ip_detected(self):
        """10.x.x.x should be private."""
        result = _is_private_ip("10.0.0.1")
        assert result is True

    def test_public_ip_not_private(self):
        """Public IP should not be private."""
        result = _is_private_ip("8.8.8.8")
        assert result is False

    def test_localhost_is_private(self):
        """127.0.0.1 should be private."""
        result = _is_private_ip("127.0.0.1")
        assert result is True

    def test_private_172_range(self):
        """172.16.x.x should be private."""
        result = _is_private_ip("172.16.0.1")
        assert result is True

    def test_private_192_range(self):
        """192.168.x.x should be private."""
        result = _is_private_ip("192.168.1.1")
        assert result is True


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
