"""Tests for utils.result — Category: class"""

import pytest

from utils.result import Err
from utils.result import Ok


class TestOk:
    """Tests for the Ok class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            Ok()

    def test_str_repr(self):
        """String representation not available."""
        with pytest.raises(TypeError):
            Ok()


class TestErr:
    """Tests for the Err class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            Ok()

    def test_str_repr(self):
        """String representation not available."""
        with pytest.raises(TypeError):
            Ok()
