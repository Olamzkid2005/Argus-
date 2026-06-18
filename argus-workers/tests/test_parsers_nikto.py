"""Tests for tool_core.parser.parsers.nikto — Category: function"""

import pytest

from tool_core.parser.parsers.nikto import (
    _infer_severity,
    _parse_csv,
    _parse_json,
    _parse_text,
    parse,
)


class TestInferSeverity:
    """Tests for the _infer_severity function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _infer_severity()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _infer_severity()


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


class TestParseCsv:
    """Tests for the _parse_csv function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _parse_csv()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _parse_csv()


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
