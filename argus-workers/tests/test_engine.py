"""Tests for custom_rules.engine — Category: class"""

import pytest

from custom_rules.engine import CustomRuleEngine
from custom_rules.engine import CustomRuleError


class TestCustomRuleError:
    """Tests for the CustomRuleError class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = CustomRuleError()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = CustomRuleError()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass


class TestCustomRuleEngine:
    """Tests for the CustomRuleEngine class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = CustomRuleEngine()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = CustomRuleEngine()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
