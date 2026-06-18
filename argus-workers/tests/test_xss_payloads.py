"""Tests for tools.web_scanner_checks.payloads.xss_payloads — Category: function"""


from tools.web_scanner_checks.payloads.xss_payloads import get_xss_payloads


class TestGetXssPayloads:
    """Tests for the get_xss_payloads function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        instance = get_xss_payloads()
        assert instance is not None

    def test_returns_correct_type(self):
        """Returns a list of payloads."""
        instance = get_xss_payloads()
        assert isinstance(instance, list)
