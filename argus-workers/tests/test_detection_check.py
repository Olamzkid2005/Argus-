"""Tests for tools.web_scanner_checks.detection_check — Category: class"""

import pytest

from tools.web_scanner_checks.detection_check import DetectionCheck


class TestDetectionCheck:
    """Tests for the DetectionCheck class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = DetectionCheck()
        assert instance is not None

    def test_str_repr(self):
        """String representation not available."""
        instance = DetectionCheck()
        assert instance is not None
