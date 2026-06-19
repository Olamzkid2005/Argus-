"""Tests for tools.web_scanner_checks.payloads.ssti_payloads — Category: function"""


from tools.web_scanner_checks.payloads.ssti_payloads import get_ssti_payloads


class TestGetSstiPayloads:
    """Tests for the get_ssti_payloads function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        instance = get_ssti_payloads()
        assert instance is not None

    def test_returns_correct_type(self):
        """Returns a list."""
        instance = get_ssti_payloads()
        assert isinstance(instance, list)
