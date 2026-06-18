"""Tests for tools.web_scanner_checks.network_check — Category: class"""

import pytest

from tools.web_scanner_checks.network_check import NetworkCheck


class TestNetworkCheck:
    """Tests for the NetworkCheck class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = NetworkCheck()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = NetworkCheck()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
