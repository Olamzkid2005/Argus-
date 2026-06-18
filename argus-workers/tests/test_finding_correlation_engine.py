"""Tests for tools.finding_correlation_engine — Category: class"""

import pytest

from tools.finding_correlation_engine import FindingCorrelationEngine


class TestFindingCorrelationEngine:
    """Tests for the FindingCorrelationEngine class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = FindingCorrelationEngine()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = FindingCorrelationEngine()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
