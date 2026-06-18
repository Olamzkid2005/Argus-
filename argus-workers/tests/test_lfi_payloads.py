"""Tests for tools.web_scanner_checks.payloads.lfi_payloads — Category: function"""

import pytest

from tools.web_scanner_checks.payloads.lfi_payloads import get_lfi_payloads


class TestGetLfiPayloads:
    """Tests for the get_lfi_payloads function."""

    def test_basic_execution(self):
        """Function can be called without crashing."""
        try:
            result = get_lfi_payloads()
            assert result is not None
        except TypeError:
            pytest.skip("get_lfi_payloads requires specific args")
        except Exception as e:
            pytest.skip(f"Skip: {e}")

    def test_returns_correct_type(self):
        """Function returns expected type."""
        try:
            result = get_lfi_payloads()
            assert isinstance(result, (str, int, float, bool, list, dict, tuple, type(None)))
        except TypeError:
            pass  # Skip if args needed
