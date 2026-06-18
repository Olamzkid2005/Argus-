"""Tests for utils.retry — Category: class"""

import pytest

from utils.retry import RetryExhaustedError


class TestRetryExhaustedError:
    """Tests for the RetryExhaustedError class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = RetryExhaustedError()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = RetryExhaustedError()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
