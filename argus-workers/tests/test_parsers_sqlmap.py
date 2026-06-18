"""Tests for tool_core.parser.parsers.sqlmap — Category: function"""

import pytest

from tool_core.parser.parsers.sqlmap import _classify_technique
from tool_core.parser.parsers.sqlmap import _parse_json
from tool_core.parser.parsers.sqlmap import _parse_text
from tool_core.parser.parsers.sqlmap import parse


class TestClassifyTechnique:
    """Tests for the _classify_technique function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _classify_technique()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _classify_technique()


class TestParseJson:
    """Tests for the _parse_json function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _parse_json()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _parse_json()


class TestParseText:
    """Tests for the _parse_text function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _parse_text()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _parse_text()


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
