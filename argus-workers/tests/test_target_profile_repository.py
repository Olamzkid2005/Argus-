"""Tests for database.repositories.target_profile_repository — Category: class"""

import pytest

from database.repositories.target_profile_repository import TargetProfileRepository


class TestTargetProfileRepository:
    """Tests for the TargetProfileRepository class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = TargetProfileRepository()
        assert instance is not None

    def test_str_repr(self):
        """String representation not available."""
        instance = TargetProfileRepository()
        assert instance is not None
