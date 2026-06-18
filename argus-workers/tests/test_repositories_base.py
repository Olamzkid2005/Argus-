"""Tests for database.repositories.base — Category: class"""

import pytest

from database.repositories.base import BaseRepository


class TestBaseRepository:
    """Tests for the BaseRepository class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = BaseRepository()
        assert instance is not None

    def test_str_repr(self):
        """String representation not available."""
        instance = BaseRepository()
        assert instance is not None
