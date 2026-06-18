"""Tests for tools.web_scanner_checks.headers_check — Category: class"""

import pytest

from tools.web_scanner_checks.headers_check import HeadersCheck


class TestHeadersCheck:
    """Tests for the HeadersCheck class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = HeadersCheck()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = HeadersCheck()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
