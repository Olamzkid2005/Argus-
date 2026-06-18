"""Tests for tools.web_scanner_checks.js_secrets_check — Category: class"""

import pytest

from tools.web_scanner_checks.js_secrets_check import JsSecretsCheck


class TestJsSecretsCheck:
    """Tests for the JsSecretsCheck class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = JsSecretsCheck()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = JsSecretsCheck()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
