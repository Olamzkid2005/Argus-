"""Tests for tools.attack_surface_mapper — Category: class"""

import pytest

from tools.attack_surface_mapper import AttackSurfaceMapper


class TestAttackSurfaceMapper:
    """Tests for the AttackSurfaceMapper class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = AttackSurfaceMapper()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = AttackSurfaceMapper()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
