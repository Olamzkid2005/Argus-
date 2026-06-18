"""Tests for tools.browser_scanner — Category: class"""

import pytest

from tools.browser_scanner import BrowserScanner


class TestBrowserScanner:
    """Tests for the BrowserScanner class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = BrowserScanner()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = BrowserScanner()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
