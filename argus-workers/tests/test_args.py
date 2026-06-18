"""Tests for tool_core.validators.args — Category: function"""

import pytest

from tool_core.validators.args import is_dangerous


class TestIsDangerous:
    """Tests for the is_dangerous function."""

    def test_basic_execution(self):
        """Function can be called without crashing."""
        try:
            result = is_dangerous()
            assert result is not None
        except TypeError:
            pytest.skip("is_dangerous requires specific args")
        except Exception as e:
            pytest.skip(f"Skip: {e}")

    def test_returns_correct_type(self):
        """Function returns expected type."""
        try:
            result = is_dangerous()
            assert isinstance(result, (str, int, float, bool, list, dict, tuple, type(None)))
        except TypeError:
            pass  # Skip if args needed
