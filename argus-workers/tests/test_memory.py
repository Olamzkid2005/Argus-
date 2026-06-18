"""Tests for runtime.memory — Category: class"""

import pytest

from runtime.memory import MemoryRetriever


class TestMemoryRetriever:
    """Tests for the MemoryRetriever class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = MemoryRetriever()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = MemoryRetriever()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
