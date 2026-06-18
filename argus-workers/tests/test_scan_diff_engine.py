"""Tests for scan_diff_engine — Category: class"""

import pytest

from scan_diff_engine import ScanDiffEngine


class TestScanDiffEngine:
    """Tests for the ScanDiffEngine class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = ScanDiffEngine()
        assert instance is not None

    def test_str_repr(self):
        """String representation not available."""
        instance = ScanDiffEngine()
        assert instance is not None
