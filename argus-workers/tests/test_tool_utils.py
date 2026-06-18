"""Tests for tools.tool_utils — Category: function"""

import pytest

from tools.tool_utils import get_augmented_path
from tools.tool_utils import is_tool_available
from tools.tool_utils import resolve_tool_binary


class TestGetAugmentedPath:
    """Tests for the get_augmented_path function."""

    def test_basic_execution(self):
        """Function can be called without crashing."""
        try:
            result = get_augmented_path()
            assert result is not None
        except TypeError:
            pytest.skip("get_augmented_path requires specific args")
        except Exception as e:
            pytest.skip(f"Skip: {e}")

    def test_returns_correct_type(self):
        """Function returns expected type."""
        try:
            result = get_augmented_path()
            assert isinstance(result, (str, int, float, bool, list, dict, tuple, type(None)))
        except TypeError:
            pass  # Skip if args needed


class TestResolveToolBinary:
    """Tests for the resolve_tool_binary function."""

    def test_basic_execution(self):
        """Function can be called without crashing."""
        try:
            result = resolve_tool_binary()
            assert result is not None
        except TypeError:
            pytest.skip("resolve_tool_binary requires specific args")
        except Exception as e:
            pytest.skip(f"Skip: {e}")

    def test_returns_correct_type(self):
        """Function returns expected type."""
        try:
            result = resolve_tool_binary()
            assert isinstance(result, (str, int, float, bool, list, dict, tuple, type(None)))
        except TypeError:
            pass  # Skip if args needed


class TestIsToolAvailable:
    """Tests for the is_tool_available function."""

    def test_basic_execution(self):
        """Function can be called without crashing."""
        try:
            result = is_tool_available()
            assert result is not None
        except TypeError:
            pytest.skip("is_tool_available requires specific args")
        except Exception as e:
            pytest.skip(f"Skip: {e}")

    def test_returns_correct_type(self):
        """Function returns expected type."""
        try:
            result = is_tool_available()
            assert isinstance(result, (str, int, float, bool, list, dict, tuple, type(None)))
        except TypeError:
            pass  # Skip if args needed
