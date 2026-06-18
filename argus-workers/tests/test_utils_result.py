"""Tests for utils.result — Category: class"""

import pytest

from utils.result import Err


class TestOk:
    """Tests for the Ok class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            Err()

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            Err()
            str(Err())


class TestErr:
    """Tests for the Err class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            Err()

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            Err()
            str(Err())
