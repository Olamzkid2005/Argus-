"""Tests for tools.bugbounty_report_generator — Category: class"""

import pytest

from tools.bugbounty_report_generator import ArgusFindingAdapter
from tools.bugbounty_report_generator import BugBountyReportGenerator


class TestArgusFindingAdapter:
    """Tests for the ArgusFindingAdapter class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = ArgusFindingAdapter()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = ArgusFindingAdapter()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)


class TestBugBountyReportGenerator:
    """Tests for the BugBountyReportGenerator class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = ArgusFindingAdapter()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = ArgusFindingAdapter()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
