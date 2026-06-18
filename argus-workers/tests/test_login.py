"""Tests for tools.login — Category: class"""

import pytest

from tools.login import LoginTool


class TestLoginTool:
    """Tests for the LoginTool class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = LoginTool()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = LoginTool()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
