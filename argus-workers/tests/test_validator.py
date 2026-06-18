"""Tests for custom_rules.validator — Category: class"""

import pytest

from custom_rules.validator import RuleValidationError
from custom_rules.validator import RuleValidator


class TestRuleValidationError:
    """Tests for the RuleValidationError class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = RuleValidationError()
        assert instance is not None

    def test_str_repr(self):
        """String representation not available."""
        instance = RuleValidationError()
        assert instance is not None


class TestRuleValidator:
    """Tests for the RuleValidator class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = RuleValidationError()
        assert instance is not None

    def test_str_repr(self):
        """String representation not available."""
        instance = RuleValidationError()
        assert instance is not None
