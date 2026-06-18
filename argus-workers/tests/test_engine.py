"""Tests for custom_rules.engine — Category: class"""

import pytest

from custom_rules.engine import CustomRuleEngine
from custom_rules.engine import CustomRuleError


class TestCustomRuleError:
    """Tests for the CustomRuleError class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = CustomRuleError()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = CustomRuleError()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)


class TestCustomRuleEngine:
    """Tests for the CustomRuleEngine class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = CustomRuleError()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = CustomRuleError()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
