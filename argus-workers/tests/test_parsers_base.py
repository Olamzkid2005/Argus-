"""Tests for parsers.parsers.base — Category: error"""

import pytest

from parsers.parsers.base import ParserError


class TestParserError:
    """Tests for the ParserError exception."""

    def test_is_exception(self):
        """ParserError is an exception class."""
        assert issubclass(ParserError, Exception)

    def test_can_be_raised(self):
        """Can be raised and caught."""
        try:
            raise ParserError("test error")
        except ParserError as e:
            assert str(e) == "test error"


class TestBaseParser:
    """BaseParser is abstract — verify it cannot be instantiated."""

    def test_abstract_cannot_instantiate(self):
        """Cannot instantiate abstract BaseParser."""
        from parsers.parsers.base import BaseParser
        with pytest.raises(TypeError):
            BaseParser()
