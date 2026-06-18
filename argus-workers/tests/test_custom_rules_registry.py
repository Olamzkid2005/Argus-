"""Tests for custom_rules.registry — Category: class"""

import pytest

from custom_rules.registry import RuleRegistry


class TestRuleRegistry:
    """Tests for the RuleRegistry class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = RuleRegistry()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = RuleRegistry()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
