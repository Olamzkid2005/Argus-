"""Tests for custom_rules.registry — Category: class"""

import pytest

from custom_rules.registry import RuleRegistry


class TestRuleRegistry:
    """Tests for the RuleRegistry class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = RuleRegistry()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = RuleRegistry()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
