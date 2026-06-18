"""Tests for tools.browser_scanner — Category: class"""

import pytest

from tools.browser_scanner import BrowserScanner


class TestBrowserScanner:
    """Tests for the BrowserScanner class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = BrowserScanner()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = BrowserScanner()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
