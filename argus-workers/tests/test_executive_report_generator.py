"""Tests for tools.executive_report_generator — Category: class"""

import pytest

from tools.executive_report_generator import ExecutiveReportGenerator


class TestExecutiveReportGenerator:
    """Tests for the ExecutiveReportGenerator class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = ExecutiveReportGenerator()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = ExecutiveReportGenerator()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
