"""Tests for tools.attack_surface.subdomain_discovery — Category: class"""


from tools.attack_surface.subdomain_discovery import SubdomainDiscovery


class TestSubdomainDiscovery:
    """Tests for the SubdomainDiscovery class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = SubdomainDiscovery()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = SubdomainDiscovery()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
