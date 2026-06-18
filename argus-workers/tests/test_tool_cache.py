"""Tests for tools.tool_cache — Category: class"""

import pytest

from tools.tool_cache import ToolCache


class TestToolCache:
    """Tests for the ToolCache class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = ToolCache()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = ToolCache()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
