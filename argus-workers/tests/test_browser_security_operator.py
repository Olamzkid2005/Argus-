"""Tests for tools.browser_security_operator — Category: class"""

import pytest

from tools.browser_security_operator import BrowserSecurityOperator


class TestBrowserSecurityOperator:
    """Tests for the BrowserSecurityOperator class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = BrowserSecurityOperator()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = BrowserSecurityOperator()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
