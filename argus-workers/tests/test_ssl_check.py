"""Smoke tests for tools/web_scanner_checks/ssl_check.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.web_scanner_checks.ssl_check."""

    def test_module_imports(self):
        """Verify ssl_check.py imports cleanly."""
        mod = importlib.import_module("tools.web_scanner_checks.ssl_check")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class SslCheck is available."""
        mod = importlib.import_module("tools.web_scanner_checks.ssl_check")
        assert hasattr(mod, "SslCheck")
        assert callable(mod.SslCheck)

    def test_function_run_check_exists(self):
        """Verify function run_check is exported."""
        mod = importlib.import_module("tools.web_scanner_checks.ssl_check")
        assert hasattr(mod, "run_check")
        assert callable(mod.run_check)
