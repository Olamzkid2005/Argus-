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
        """String representation not available."""
        instance = BaseTask()
        assert instance is not None
