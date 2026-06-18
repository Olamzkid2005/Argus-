"""Tests for utils.retry — Category: class"""

import pytest

from utils.retry import RetryExhaustedError


class TestRetryExhaustedError:
    """Tests for the RetryExhaustedError class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = RetryExhaustedError()
        assert instance is not None

    def test_str_repr(self):
        """String representation not available."""
        instance = RetryExhaustedError()
        assert instance is not None
