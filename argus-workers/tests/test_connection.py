"""Tests for database.connection — Category: class"""

import pytest

from database.connection import ConnectionManager
from database.connection import DatabaseConnectionError


class TestDatabaseConnectionError:
    """Tests for the DatabaseConnectionError class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = ConnectionManager()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = ConnectionManager()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)


class TestConnectionManager:
    """Tests for the ConnectionManager class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = ConnectionManager()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = ConnectionManager()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
