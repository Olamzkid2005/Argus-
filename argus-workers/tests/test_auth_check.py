"""Tests for tools.web_scanner_checks.auth_check — Category: class"""


from tools.web_scanner_checks.auth_check import AuthCheck


class TestAuthCheck:
    """Tests for the AuthCheck class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = AuthCheck()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = AuthCheck()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
