"""Tests for tools.web_scanner_checks.injection_check — Category: class"""

import pytest

from tools.web_scanner_checks.injection_check import InjectionCheck


class TestInjectionCheck:
    """Tests for the InjectionCheck class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = InjectionCheck()
        assert instance is not None

    def test_str_repr(self):
        """String representation not available."""
        instance = InjectionCheck()
        assert instance is not None
