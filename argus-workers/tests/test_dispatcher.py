"""Tests for tool_core.parser.dispatcher — Category: function"""

import pytest

from tool_core.parser.dispatcher import dispatch
from tool_core.parser.dispatcher import has_parser


class TestDispatch:
    """Tests for the dispatch function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            dispatch()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        pytest.skip("Requires arguments")  # Skip if args needed


class TestHasParser:
    """Tests for the has_parser function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            dispatch()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        pytest.skip("Requires arguments")  # Skip if args needed
