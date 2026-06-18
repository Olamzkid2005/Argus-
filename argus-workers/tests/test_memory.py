"""Tests for runtime.memory — Category: class"""

import pytest

from runtime.memory import MemoryRetriever


class TestMemoryRetriever:
    """Tests for the MemoryRetriever class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = MemoryRetriever()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = MemoryRetriever()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
