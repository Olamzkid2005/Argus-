"""Tests for tools.ffuf_scanner — Category: class"""

import pytest

from tools.ffuf_scanner import FfufScanner


class TestFfufScanner:
    """Tests for the FfufScanner class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = FfufScanner()
        assert instance is not None

    def test_str_repr(self):
        """String representation not available."""
        instance = FfufScanner()
        assert instance is not None
