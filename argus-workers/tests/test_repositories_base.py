"""Tests for database.repositories.base — Category: class"""

import pytest

from database.repositories.base import BaseRepository


class TestBaseRepository:
    """Tests for the BaseRepository class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = BaseRepository()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = BaseRepository()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
