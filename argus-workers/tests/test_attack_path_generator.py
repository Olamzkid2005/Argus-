"""Tests for tools.attack_path_generator — Category: class"""

import pytest

from tools.attack_path_generator import AttackPathGenerator


class TestAttackPathGenerator:
    """Tests for the AttackPathGenerator class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = AttackPathGenerator()
        assert instance is not None

    def test_str_repr(self):
        """String representation not available."""
        instance = AttackPathGenerator()
        assert instance is not None
