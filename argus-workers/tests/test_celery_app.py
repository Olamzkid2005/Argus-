"""Tests for celery_app — Category: class"""

import pytest

from celery_app import BaseTask


class TestBaseTask:
    """Tests for the BaseTask class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = BaseTask()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = BaseTask()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
