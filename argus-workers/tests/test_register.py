"""Tests for tools.register — Category: class"""

import pytest

from tools.register import RegisterTool


class TestRegisterTool:
    """Tests for the RegisterTool class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = RegisterTool()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = RegisterTool()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
