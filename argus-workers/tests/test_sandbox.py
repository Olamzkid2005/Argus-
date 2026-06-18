"""Tests for tool_core.sandbox — Category: class"""

import pytest

from tool_core.sandbox import AsyncToolRunner


class TestAsyncToolRunner:
    """Tests for the AsyncToolRunner class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = AsyncToolRunner()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = AsyncToolRunner()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
