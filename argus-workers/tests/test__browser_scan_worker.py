"""Tests for tools._browser_scan_worker — Category: function"""

import pytest

pytest.importorskip("playwright")

from tools._browser_scan_worker import _validate_url, scan


class TestValidateUrl:
    """Tests for the _validate_url function."""

    def test_valid_url(self):
        """Valid URL returns the URL."""
        result = _validate_url("https://example.com")
        assert result == "https://example.com"

    def test_invalid_url_raises(self):
        """Invalid URL raises ValueError."""
        with pytest.raises((ValueError, TypeError)):
            _validate_url("")


class TestScan:
    """Tests for the scan function."""

    def test_requires_target(self):
        """Requires a target URL."""
        with pytest.raises(TypeError):
            scan()
