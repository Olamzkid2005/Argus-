"""Tests for tools.web_scanner_checks.ssl_check — Category: class"""


from tools.web_scanner_checks.ssl_check import SslCheck


class TestSslCheck:
    """Tests for the SslCheck class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = SslCheck()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = SslCheck()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
