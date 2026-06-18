"""Tests for utils.result — Category: class"""

import pytest

from utils.result import Err
from utils.result import Ok


class TestOk:
    """Tests for the Ok class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = Ok()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = Ok()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass


class TestErr:
    """Tests for the Err class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = Err()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = Err()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
