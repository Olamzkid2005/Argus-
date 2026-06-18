"""Tests for tools.web_scanner_checks.response_check — Category: class"""

import pytest

from tools.web_scanner_checks.response_check import ResponseCheck


class TestResponseCheck:
    """Tests for the ResponseCheck class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = ResponseCheck()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = ResponseCheck()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
