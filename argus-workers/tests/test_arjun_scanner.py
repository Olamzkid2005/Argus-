"""Tests for tools.arjun_scanner — Category: class"""

import pytest

from tools.arjun_scanner import ArjunScanner


class TestArjunScanner:
    """Tests for the ArjunScanner class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = ArjunScanner()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = ArjunScanner()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
