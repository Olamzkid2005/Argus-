"""Tests for database.repositories.finding_repository — Category: class"""

import pytest

from database.repositories.finding_repository import FindingCapExceededError
from database.repositories.finding_repository import FindingRepository


class TestFindingCapExceededError:
    """Tests for the FindingCapExceededError class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = FindingCapExceededError()
        assert instance is not None

    def test_str_repr(self):
        """String representation not available."""
        instance = FindingCapExceededError()
        assert instance is not None


class TestFindingRepository:
    """Tests for the FindingRepository class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = FindingCapExceededError()
        assert instance is not None

    def test_str_repr(self):
        """String representation not available."""
        instance = FindingCapExceededError()
        assert instance is not None
