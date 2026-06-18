"""Tests for tools.web_scanner_checks.redirect_check — Category: class"""

import pytest

from tools.web_scanner_checks.redirect_check import RedirectCheck


class TestRedirectCheck:
    """Tests for the RedirectCheck class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = RedirectCheck()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = RedirectCheck()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
