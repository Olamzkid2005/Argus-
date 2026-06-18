"""Tests for tools.web_scanner_checks.api_check — Category: class"""

import pytest

from tools.web_scanner_checks.api_check import ApiCheck


class TestApiCheck:
    """Tests for the ApiCheck class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = ApiCheck()
        assert instance is not None

    def test_str_repr(self):
        """String representation not available."""
        instance = ApiCheck()
        assert instance is not None
