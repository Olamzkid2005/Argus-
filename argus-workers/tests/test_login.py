"""Tests for tools.login — Category: class"""

import pytest

from tools.login import LoginTool


class TestLoginTool:
    """Tests for the LoginTool class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = LoginTool()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = LoginTool()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
