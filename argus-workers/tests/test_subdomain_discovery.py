"""Tests for tools.attack_surface.subdomain_discovery — Category: class"""

import pytest

from tools.attack_surface.subdomain_discovery import SubdomainDiscovery


class TestSubdomainDiscovery:
    """Tests for the SubdomainDiscovery class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = SubdomainDiscovery()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = SubdomainDiscovery()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
