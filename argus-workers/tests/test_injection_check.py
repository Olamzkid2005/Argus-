"""Tests for tools.web_scanner_checks.injection_check — Category: class"""


from tools.web_scanner_checks.injection_check import InjectionCheck


class TestInjectionCheck:
    """Tests for the InjectionCheck class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = InjectionCheck()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = InjectionCheck()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
