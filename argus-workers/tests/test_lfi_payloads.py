"""Tests for tools.web_scanner_checks.payloads.lfi_payloads — Category: function"""


from tools.web_scanner_checks.payloads.lfi_payloads import get_lfi_payloads


class TestGetLfiPayloads:
    """Tests for the get_lfi_payloads function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        instance = get_lfi_payloads()
        assert instance is not None

    def test_returns_correct_type(self):
        """Returns a list."""
        instance = get_lfi_payloads()
        assert isinstance(instance, list)
