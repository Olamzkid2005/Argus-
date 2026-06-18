"""Tests for database.repositories.target_profile_repository — Category: class"""


from database.repositories.target_profile_repository import TargetProfileRepository


class TestTargetProfileRepository:
    """Tests for the TargetProfileRepository class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = TargetProfileRepository()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = TargetProfileRepository()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
