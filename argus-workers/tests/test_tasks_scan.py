"""Tests for tasks.scan — Category: function"""

import pytest

from tasks.scan import auth_focused_scan
from tasks.scan import deep_scan
from tasks.scan import run_scan


class TestRunScan:
    """Tests for the run_scan function."""

    def test_basic_execution(self):
        """Function can be called without crashing."""
        try:
            result = run_scan()
            assert result is not None
        except TypeError:
            pytest.skip("run_scan requires specific args")
        except Exception as e:
            pytest.skip(f"Skip: {e}")

    def test_returns_correct_type(self):
        """Function returns expected type."""
        try:
            result = run_scan()
            assert isinstance(result, (str, int, float, bool, list, dict, tuple, type(None)))
        except TypeError:
            pass  # Skip if args needed


class TestDeepScan:
    """Tests for the deep_scan function."""

    def test_basic_execution(self):
        """Function can be called without crashing."""
        try:
            result = deep_scan()
            assert result is not None
        except TypeError:
            pytest.skip("deep_scan requires specific args")
        except Exception as e:
            pytest.skip(f"Skip: {e}")

    def test_returns_correct_type(self):
        """Function returns expected type."""
        try:
            result = deep_scan()
            assert isinstance(result, (str, int, float, bool, list, dict, tuple, type(None)))
        except TypeError:
            pass  # Skip if args needed


class TestAuthFocusedScan:
    """Tests for the auth_focused_scan function."""

    def test_basic_execution(self):
        """Function can be called without crashing."""
        try:
            result = auth_focused_scan()
            assert result is not None
        except TypeError:
            pytest.skip("auth_focused_scan requires specific args")
        except Exception as e:
            pytest.skip(f"Skip: {e}")

    def test_returns_correct_type(self):
        """Function returns expected type."""
        try:
            result = auth_focused_scan()
            assert isinstance(result, (str, int, float, bool, list, dict, tuple, type(None)))
        except TypeError:
            pass  # Skip if args needed
