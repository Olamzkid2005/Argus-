"""Tests for tools.web_scanner_checks.headers_check — Category: class"""

import pytest

from tools.web_scanner_checks.headers_check import HeadersCheck


class TestHeadersCheck:
    """Tests for the HeadersCheck class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = HeadersCheck()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = HeadersCheck()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
