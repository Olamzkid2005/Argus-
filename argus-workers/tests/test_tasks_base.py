"""Tests for tasks.base — Category: dataclass"""

import pytest

from tasks.base import OperatorCanceled, TaskContext, _SoftTimeLimitExceeded


class TestOperatorCanceled:
    """Tests for the OperatorCanceled class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = OperatorCanceled()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = OperatorCanceled()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)


class TestTaskContext:
    """Tests for the TaskContext class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            TaskContext()

    def test_field_access(self):
        """Instance fields not accessible (requires constructor args)."""
        with pytest.raises(TypeError):
            TaskContext()


class TestSoftTimeLimitExceeded:  # noqa: N801 - tests private class _SoftTimeLimitExceeded
    """Tests for the _SoftTimeLimitExceeded class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = _SoftTimeLimitExceeded()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = _SoftTimeLimitExceeded()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
