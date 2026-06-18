"""Tests for tools.web_scanner_checks.redirect_check — Category: class"""


from tools.web_scanner_checks.redirect_check import RedirectCheck


class TestRedirectCheck:
    """Tests for the RedirectCheck class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = RedirectCheck()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = RedirectCheck()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
