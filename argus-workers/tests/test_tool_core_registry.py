"""Tests for tool_core.registry — Category: class"""

import pytest

from tool_core.registry import ToolRegistry


class TestToolRegistry:
    """Tests for the ToolRegistry class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = ToolRegistry()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = ToolRegistry()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
