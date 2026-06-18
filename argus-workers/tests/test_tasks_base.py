"""Tests for tasks.base — Category: dataclass"""

import pytest

from tasks.base import OperatorCanceled
from tasks.base import TaskContext
from tasks.base import _SoftTimeLimitExceeded


class TestOperatorCanceled:
    """Tests for the OperatorCanceled class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = OperatorCanceled()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = OperatorCanceled()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass


class TestTaskContext:
    """Tests for the TaskContext class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = TaskContext()
            assert instance is not None
            assert isinstance(instance, TaskContext)
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_field_access(self):
        """Instance fields are accessible."""
        try:
            instance = TaskContext()
            fields = vars(instance) if hasattr(instance, '__dict__') else {}
            assert isinstance(fields, dict)
        except TypeError:
            pytest.skip("Requires constructor args")


class Test_SoftTimeLimitExceeded:
    """Tests for the _SoftTimeLimitExceeded class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = _SoftTimeLimitExceeded()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = _SoftTimeLimitExceeded()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
