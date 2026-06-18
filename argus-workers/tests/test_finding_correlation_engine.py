"""Tests for tools.finding_correlation_engine — Category: class"""

import pytest

from tools.finding_correlation_engine import FindingCorrelationEngine


class TestFindingCorrelationEngine:
    """Tests for the FindingCorrelationEngine class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = FindingCorrelationEngine()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = FindingCorrelationEngine()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
