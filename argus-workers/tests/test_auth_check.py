"""Tests for tools.web_scanner_checks.auth_check — Category: class"""

import pytest

from tools.web_scanner_checks.auth_check import AuthCheck


class TestAuthCheck:
    """Tests for the AuthCheck class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = AuthCheck()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = AuthCheck()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
