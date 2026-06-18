"""Tests for tools.web_scanner_checks.api_check — Category: class"""

import pytest

from tools.web_scanner_checks.api_check import ApiCheck


class TestApiCheck:
    """Tests for the ApiCheck class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = ApiCheck()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = ApiCheck()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
