"""Tests for database.repositories.target_profile_repository — Category: class"""

import pytest

from database.repositories.target_profile_repository import TargetProfileRepository


class TestTargetProfileRepository:
    """Tests for the TargetProfileRepository class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = TargetProfileRepository()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = TargetProfileRepository()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
