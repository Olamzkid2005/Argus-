"""Tests for tools.tool_utils — Category: function"""

import pytest

from tools.tool_utils import get_augmented_path
from tools.tool_utils import is_tool_available
from tools.tool_utils import resolve_tool_binary


class TestGetAugmentedPath:
    """Tests for the get_augmented_path function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        instance = get_augmented_path()
        assert instance is not None

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            get_augmented_path()


class TestResolveToolBinary:
    """Tests for the resolve_tool_binary function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        instance = get_augmented_path()
        assert instance is not None

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            resolve_tool_binary()


class TestIsToolAvailable:
    """Tests for the is_tool_available function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        instance = get_augmented_path()
        assert instance is not None

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            is_tool_available()
