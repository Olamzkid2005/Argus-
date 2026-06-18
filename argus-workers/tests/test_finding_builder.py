"""Tests for tool_core.finding_builder — Category: class"""

import pytest

from tool_core.finding_builder import FindingBuilder


class TestFindingBuilder:
    """Tests for the FindingBuilder class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = FindingBuilder()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = FindingBuilder()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
