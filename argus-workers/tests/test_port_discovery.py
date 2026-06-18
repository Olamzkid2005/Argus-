"""Tests for tools.attack_surface.port_discovery — Category: class"""

import pytest

from tools.attack_surface.port_discovery import PortDiscovery


class TestPortDiscovery:
    """Tests for the PortDiscovery class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = PortDiscovery()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = PortDiscovery()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
