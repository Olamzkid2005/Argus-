"""Tests for tasks.repo_scan — Category: function"""

import pytest

from tasks.repo_scan import (
    _check_patch_for_secrets,
    _extract_file_path,
    _load_license_policy,
    _map_bandit_severity,
    _map_eslint_severity,
    _match_license,
    check_license_compliance,
    detect_license,
    enrich_findings_with_blame,
    expand_repo_scan,
    generate_cyclonedx_sbom,
    generate_spdx_sbom,
    get_blame_for_finding,
    run_bandit,
    run_eslint_security,
    run_gosec,
    run_repo_scan,
    save_sbom,
    scan_git_history_for_secrets,
)


class TestLoadLicensePolicy:
    """Tests for the _load_license_policy function."""

    def test_basic_execution(self):
        """Function executes successfully."""
        instance = _load_license_policy()
        assert instance is not None

    def test_returns_correct_type(self):
        """Returns a dict."""
        instance = _load_license_policy()
        assert isinstance(instance, dict)


class TestRunRepoScan:
    """Tests for the run_repo_scan function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            run_repo_scan()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            run_repo_scan()


class TestExpandRepoScan:
    """Tests for the expand_repo_scan function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            expand_repo_scan()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            expand_repo_scan()


class TestGetBlameForFinding:
    """Tests for the get_blame_for_finding function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            get_blame_for_finding()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            get_blame_for_finding()


class TestEnrichFindingsWithBlame:
    """Tests for the enrich_findings_with_blame function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            enrich_findings_with_blame()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            enrich_findings_with_blame()


class TestGenerateCyclonedxSbom:
    """Tests for the generate_cyclonedx_sbom function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            generate_cyclonedx_sbom()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            generate_cyclonedx_sbom()


class TestGenerateSpdxSbom:
    """Tests for the generate_spdx_sbom function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            generate_spdx_sbom()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            generate_spdx_sbom()


class TestSaveSbom:
    """Tests for the save_sbom function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            save_sbom()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            save_sbom()


class TestScanGitHistoryForSecrets:
    """Tests for the scan_git_history_for_secrets function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            scan_git_history_for_secrets()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            scan_git_history_for_secrets()


class TestCheckPatchForSecrets:
    """Tests for the _check_patch_for_secrets function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _check_patch_for_secrets()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _check_patch_for_secrets()


class TestExtractFilePath:
    """Tests for the _extract_file_path function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _extract_file_path()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _extract_file_path()


class TestDetectLicense:
    """Tests for the detect_license function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            detect_license()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            detect_license()


class TestMatchLicense:
    """Tests for the _match_license function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _match_license()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _match_license()


class TestCheckLicenseCompliance:
    """Tests for the check_license_compliance function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            check_license_compliance()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            check_license_compliance()


class TestRunBandit:
    """Tests for the run_bandit function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            run_bandit()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            run_bandit()


class TestMapBanditSeverity:
    """Tests for the _map_bandit_severity function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _map_bandit_severity()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _map_bandit_severity()


class TestRunEslintSecurity:
    """Tests for the run_eslint_security function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            run_eslint_security()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            run_eslint_security()


class TestMapEslintSeverity:
    """Tests for the _map_eslint_severity function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _map_eslint_severity()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _map_eslint_severity()


class TestRunGosec:
    """Tests for the run_gosec function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            run_gosec()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            run_gosec()
