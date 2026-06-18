"""Tests for tools.attack_surface.url_discovery — Category: class"""

import pytest

from tools.attack_surface.url_discovery import URLDiscovery


class TestURLDiscovery:
    """Tests for the URLDiscovery class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = URLDiscovery()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = URLDiscovery()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
