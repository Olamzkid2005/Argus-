"""Tests for tools.web_scanner_checks.config_check — Category: class"""


from tools.web_scanner_checks.config_check import ConfigCheck


class TestConfigCheck:
    """Tests for the ConfigCheck class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = ConfigCheck()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = ConfigCheck()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
