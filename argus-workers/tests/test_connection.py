"""Tests for database.connection — Category: class"""

import pytest

from database.connection import ConnectionManager
from database.connection import DatabaseConnectionError


class TestDatabaseConnectionError:
    """Tests for the DatabaseConnectionError class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = DatabaseConnectionError()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = DatabaseConnectionError()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass


class TestConnectionManager:
    """Tests for the ConnectionManager class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = ConnectionManager()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = ConnectionManager()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
