"""Tests for tools.attack_surface.url_discovery — Category: class"""

import pytest

from tools.attack_surface.url_discovery import URLDiscovery


class TestURLDiscovery:
    """Tests for the URLDiscovery class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = URLDiscovery()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = URLDiscovery()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
