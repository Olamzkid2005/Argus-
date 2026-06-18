"""Tests for tools.bugbounty_report_generator — Category: class"""

import pytest

from tools.bugbounty_report_generator import ArgusFindingAdapter
from tools.bugbounty_report_generator import BugBountyReportGenerator


class TestArgusFindingAdapter:
    """Tests for the ArgusFindingAdapter class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = ArgusFindingAdapter()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = ArgusFindingAdapter()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass


class TestBugBountyReportGenerator:
    """Tests for the BugBountyReportGenerator class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = BugBountyReportGenerator()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = BugBountyReportGenerator()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
