"""Tests for tool_core.sandbox — Category: class"""

import pytest

from tool_core.sandbox import AsyncToolRunner


class TestAsyncToolRunner:
    """Tests for the AsyncToolRunner class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = AsyncToolRunner()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = AsyncToolRunner()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
