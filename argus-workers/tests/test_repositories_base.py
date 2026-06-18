"""Tests for database.repositories.base — Category: class"""


from database.repositories.base import BaseRepository


class TestBaseRepository:
    """Tests for the BaseRepository class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = BaseRepository()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = BaseRepository()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
