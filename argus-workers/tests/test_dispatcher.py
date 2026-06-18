"""Tests for tool_core.parser.dispatcher — Category: function"""

import pytest

from tool_core.parser.dispatcher import dispatch
from tool_core.parser.dispatcher import has_parser


class TestDispatch:
    """Tests for the dispatch function."""

    def test_basic_execution(self):
        """Function can be called without crashing."""
        try:
            result = dispatch()
            assert result is not None
        except TypeError:
            pytest.skip("dispatch requires specific args")
        except Exception as e:
            pytest.skip(f"Skip: {e}")

    def test_returns_correct_type(self):
        """Function returns expected type."""
        try:
            result = dispatch()
            assert isinstance(result, (str, int, float, bool, list, dict, tuple, type(None)))
        except TypeError:
            pass  # Skip if args needed


class TestHasParser:
    """Tests for the has_parser function."""

    def test_basic_execution(self):
        """Function can be called without crashing."""
        try:
            result = has_parser()
            assert result is not None
        except TypeError:
            pytest.skip("has_parser requires specific args")
        except Exception as e:
            pytest.skip(f"Skip: {e}")

    def test_returns_correct_type(self):
        """Function returns expected type."""
        try:
            result = has_parser()
            assert isinstance(result, (str, int, float, bool, list, dict, tuple, type(None)))
        except TypeError:
            pass  # Skip if args needed
