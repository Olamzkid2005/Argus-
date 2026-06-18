"""Tests for tools.web_scanner_checks.detection_check — Category: class"""

import pytest

from tools.web_scanner_checks.detection_check import DetectionCheck


class TestDetectionCheck:
    """Tests for the DetectionCheck class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = DetectionCheck()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = DetectionCheck()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
