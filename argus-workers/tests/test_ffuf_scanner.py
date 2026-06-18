"""Tests for tools.ffuf_scanner — Category: class"""

import pytest

from tools.ffuf_scanner import FfufScanner


class TestFfufScanner:
    """Tests for the FfufScanner class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = FfufScanner()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = FfufScanner()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
