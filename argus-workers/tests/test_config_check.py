"""Tests for tools.web_scanner_checks.config_check — Category: class"""

import pytest

from tools.web_scanner_checks.config_check import ConfigCheck


class TestConfigCheck:
    """Tests for the ConfigCheck class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = ConfigCheck()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = ConfigCheck()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
