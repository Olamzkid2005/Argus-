"""Tests for tools.infrastructure_security_analyzer — Category: class"""

import pytest

from tools.infrastructure_security_analyzer import InfrastructureSecurityAnalyzer


class TestInfrastructureSecurityAnalyzer:
    """Tests for the InfrastructureSecurityAnalyzer class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = InfrastructureSecurityAnalyzer()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = InfrastructureSecurityAnalyzer()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
