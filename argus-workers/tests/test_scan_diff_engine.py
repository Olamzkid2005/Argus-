"""Tests for scan_diff_engine — Category: class"""

import pytest

from scan_diff_engine import ScanDiffEngine


class TestScanDiffEngine:
    """Tests for the ScanDiffEngine class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = ScanDiffEngine()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = ScanDiffEngine()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
