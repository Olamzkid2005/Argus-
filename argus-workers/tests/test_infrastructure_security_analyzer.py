"""Tests for tools.infrastructure_security_analyzer — Category: class"""


from tools.infrastructure_security_analyzer import InfrastructureSecurityAnalyzer


class TestInfrastructureSecurityAnalyzer:
    """Tests for the InfrastructureSecurityAnalyzer class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = InfrastructureSecurityAnalyzer()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = InfrastructureSecurityAnalyzer()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
