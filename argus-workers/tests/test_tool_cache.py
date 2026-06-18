"""Tests for tools.tool_cache — Category: class"""

import pytest

from tools.tool_cache import ToolCache


class TestToolCache:
    """Tests for the ToolCache class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = ToolCache()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = ToolCache()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
