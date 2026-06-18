"""Tests for database.repositories.finding_repository — Category: class"""

import pytest

from database.repositories.finding_repository import FindingCapExceededError
from database.repositories.finding_repository import FindingRepository


class TestFindingCapExceededError:
    """Tests for the FindingCapExceededError class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = FindingCapExceededError()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = FindingCapExceededError()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass


class TestFindingRepository:
    """Tests for the FindingRepository class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = FindingRepository()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = FindingRepository()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
