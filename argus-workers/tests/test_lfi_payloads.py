"""Tests for tools.web_scanner_checks.payloads.lfi_payloads — Category: function"""

import pytest

from tools.web_scanner_checks.payloads.lfi_payloads import get_lfi_payloads


class TestGetLfiPayloads:
    """Tests for the get_lfi_payloads function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        instance = get_lfi_payloads()
        assert instance is not None

    def test_returns_correct_type(self):
        """Function requires arguments."""
        pytest.skip("Requires arguments")  # Skip if args needed
