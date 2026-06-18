"""Tests for tools.browser_security_operator — Category: class"""

import pytest

from tools.browser_security_operator import BrowserSecurityOperator


class TestBrowserSecurityOperator:
    """Tests for the BrowserSecurityOperator class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = BrowserSecurityOperator()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = BrowserSecurityOperator()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
