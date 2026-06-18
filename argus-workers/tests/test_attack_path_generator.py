"""Tests for tools.attack_path_generator — Category: class"""


from tools.attack_path_generator import AttackPathGenerator


class TestAttackPathGenerator:
    """Tests for the AttackPathGenerator class."""

    def test_instantiation(self):
        """Default instantiation succeeds."""
        instance = AttackPathGenerator()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = AttackPathGenerator()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
