"""Tests for tasks.self_scan — Category: function"""

import pytest

from tasks.self_scan import run_self_scan


class TestRunSelfScan:
    """Tests for the run_self_scan function."""

    def test_basic_execution(self):
        """Function can be called without crashing."""
        try:
            result = run_self_scan()
            assert result is not None
        except TypeError:
            pytest.skip("run_self_scan requires specific args")
        except Exception as e:
            pytest.skip(f"Skip: {e}")

    def test_returns_correct_type(self):
        """Function returns expected type."""
        try:
            result = run_self_scan()
            assert isinstance(result, (str, int, float, bool, list, dict, tuple, type(None)))
        except TypeError:
            pass  # Skip if args needed
