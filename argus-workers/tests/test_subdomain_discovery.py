"""Tests for tools.attack_surface.subdomain_discovery — Category: class"""

import pytest

from tools.attack_surface.subdomain_discovery import SubdomainDiscovery


class TestSubdomainDiscovery:
    """Tests for the SubdomainDiscovery class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = SubdomainDiscovery()
        assert instance is not None

    def test_str_repr(self):
        """String representation not available."""
        instance = SubdomainDiscovery()
        assert instance is not None
