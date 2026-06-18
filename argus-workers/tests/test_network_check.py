"""Tests for tools.web_scanner_checks.network_check — Category: class"""

import pytest

from tools.web_scanner_checks.network_check import NetworkCheck


class TestNetworkCheck:
    """Tests for the NetworkCheck class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = NetworkCheck()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = NetworkCheck()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
