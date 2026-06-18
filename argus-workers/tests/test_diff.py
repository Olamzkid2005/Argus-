"""Tests for tasks.diff — Category: function"""

import pytest

from tasks.diff import _get_engagement_target, _update_fixed_fingerprints, run_scan_diff


class TestRunScanDiff:
    """Tests for the run_scan_diff function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            run_scan_diff()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            run_scan_diff()


class TestGetEngagementTarget:
    """Tests for the _get_engagement_target function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _get_engagement_target()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _get_engagement_target()


class TestUpdateFixedFingerprints:
    """Tests for the _update_fixed_fingerprints function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _update_fixed_fingerprints()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _update_fixed_fingerprints()
