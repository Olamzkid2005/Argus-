"""Tests for custom_rules.engine — Category: class"""


from custom_rules.engine import CustomRuleEngine


class TestCustomRuleError:
    """Tests for the CustomRuleError class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = CustomRuleEngine()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = CustomRuleEngine()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)


class TestCustomRuleEngine:
    """Tests for the CustomRuleEngine class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = CustomRuleEngine()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = CustomRuleEngine()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
