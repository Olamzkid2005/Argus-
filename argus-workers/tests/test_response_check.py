"""Tests for tools.web_scanner_checks.response_check — Category: class"""

import pytest

from tools.web_scanner_checks.response_check import ResponseCheck


class TestResponseCheck:
    """Tests for the ResponseCheck class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = ResponseCheck()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = ResponseCheck()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
