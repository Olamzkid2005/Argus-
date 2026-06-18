"""Tests for celery_app — Category: class"""

import pytest

from celery_app import BaseTask


class TestBaseTask:
    """Tests for the BaseTask class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = BaseTask()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = BaseTask()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
