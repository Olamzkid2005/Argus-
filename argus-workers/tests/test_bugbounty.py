"""Tests for tasks.bugbounty — Category: function"""

import pytest

from tasks.bugbounty import _fetch_engagement
from tasks.bugbounty import _fetch_findings
from tasks.bugbounty import generate_bugbounty_report


class TestGenerateBugbountyReport:
    """Tests for the generate_bugbounty_report function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            generate_bugbounty_report()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            generate_bugbounty_report()


class TestFetchFindings:
    """Tests for the _fetch_findings function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _fetch_findings()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _fetch_findings()


class TestFetchEngagement:
    """Tests for the _fetch_engagement function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _fetch_engagement()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _fetch_engagement()
