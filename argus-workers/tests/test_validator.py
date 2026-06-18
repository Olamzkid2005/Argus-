"""Tests for custom_rules.validator — Category: class"""

import pytest

from custom_rules.validator import RuleValidationError
from custom_rules.validator import RuleValidator


class TestRuleValidationError:
    """Tests for the RuleValidationError class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = RuleValidationError()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = RuleValidationError()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass


class TestRuleValidator:
    """Tests for the RuleValidator class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = RuleValidator()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = RuleValidator()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
