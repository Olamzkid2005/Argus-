"""Tests for scan_diff_engine — Category: class"""


from scan_diff_engine import ScanDiffEngine


class TestScanDiffEngine:
    """Tests for the ScanDiffEngine class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = ScanDiffEngine()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = ScanDiffEngine()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
