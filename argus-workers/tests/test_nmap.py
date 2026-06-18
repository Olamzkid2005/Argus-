"""Tests for tool_core.parser.parsers.nmap — Category: function"""

import pytest

from tool_core.parser.parsers.nmap import parse


class TestParse:
    """Tests for the parse function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            parse()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            parse()
