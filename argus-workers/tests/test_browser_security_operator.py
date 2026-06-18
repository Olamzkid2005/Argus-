"""Smoke tests for tools/browser_security_operator.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.browser_security_operator."""

    def test_module_imports(self):
        """Verify browser_security_operator.py imports cleanly."""
        mod = importlib.import_module("tools.browser_security_operator")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class BrowserSecurityOperator is available."""
        mod = importlib.import_module("tools.browser_security_operator")
        assert hasattr(mod, "BrowserSecurityOperator")
        assert callable(mod.BrowserSecurityOperator)
