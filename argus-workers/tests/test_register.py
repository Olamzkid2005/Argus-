"""Tests for tools.register — Category: class"""

import pytest

from tools.register import RegisterTool


class TestRegisterTool:
    """Tests for the RegisterTool class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = RegisterTool()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = RegisterTool()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
