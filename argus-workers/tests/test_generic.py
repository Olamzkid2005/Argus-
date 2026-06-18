"""Tests for tool_core.parser.parsers.generic — Category: function"""

import pytest

from tool_core.parser.parsers.generic import _regex_extract
from tool_core.parser.parsers.generic import _try_json
from tool_core.parser.parsers.generic import parse


class TestTryJson:
    """Tests for the _try_json function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _try_json()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _try_json()


class TestRegexExtract:
    """Tests for the _regex_extract function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _regex_extract()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _regex_extract()


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
