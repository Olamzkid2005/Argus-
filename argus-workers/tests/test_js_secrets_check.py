"""Tests for tools.web_scanner_checks.js_secrets_check — Category: class"""

import pytest

from tools.web_scanner_checks.js_secrets_check import JsSecretsCheck


class TestJsSecretsCheck:
    """Tests for the JsSecretsCheck class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = JsSecretsCheck()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = JsSecretsCheck()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
