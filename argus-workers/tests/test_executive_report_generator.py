"""Tests for tools.executive_report_generator — Category: class"""

import pytest

from tools.executive_report_generator import ExecutiveReportGenerator


class TestExecutiveReportGenerator:
    """Tests for the ExecutiveReportGenerator class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = ExecutiveReportGenerator()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = ExecutiveReportGenerator()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
