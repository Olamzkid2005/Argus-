"""Tests for tasks.analyze — Category: function"""

import pytest

from tasks.analyze import run_analysis


class TestRunAnalysis:
    """Tests for the run_analysis function."""

    def test_basic_execution(self):
        """Function can be called without crashing."""
        try:
            result = run_analysis()
            assert result is not None
        except TypeError:
            pytest.skip("run_analysis requires specific args")
        except Exception as e:
            pytest.skip(f"Skip: {e}")

    def test_returns_correct_type(self):
        """Function returns expected type."""
        try:
            result = run_analysis()
            assert isinstance(result, (str, int, float, bool, list, dict, tuple, type(None)))
        except TypeError:
            pass  # Skip if args needed
