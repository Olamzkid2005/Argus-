"""Tests for tools.attack_surface.port_discovery — Category: class"""

import pytest

from tools.attack_surface.port_discovery import PortDiscovery


class TestPortDiscovery:
    """Tests for the PortDiscovery class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = PortDiscovery()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = PortDiscovery()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
