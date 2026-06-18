"""Tests for tools.attack_surface_mapper — Category: class"""

import pytest

from tools.attack_surface_mapper import AttackSurfaceMapper


class TestAttackSurfaceMapper:
    """Tests for the AttackSurfaceMapper class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = AttackSurfaceMapper()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = AttackSurfaceMapper()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
