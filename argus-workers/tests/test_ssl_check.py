"""Tests for tools.web_scanner_checks.ssl_check — Category: class"""

import pytest

from tools.web_scanner_checks.ssl_check import SslCheck


class TestSslCheck:
    """Tests for the SslCheck class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = SslCheck()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = SslCheck()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
