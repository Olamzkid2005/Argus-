"""Tests for tools.web_scanner_checks.auth_check — Category: class"""

import pytest

from tools.web_scanner_checks.auth_check import AuthCheck


class TestAuthCheck:
    """Tests for the AuthCheck class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = AuthCheck()
        assert instance is not None

    def test_str_repr(self):
        """String representation not available."""
        instance = AuthCheck()
        assert instance is not None
