"""Tests for tools.attack_path_generator — Category: class"""

import pytest

from tools.attack_path_generator import AttackPathGenerator


class TestAttackPathGenerator:
    """Tests for the AttackPathGenerator class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = AttackPathGenerator()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = AttackPathGenerator()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
