"""Smoke tests for tools/web_scanner_checks/injection_check.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.web_scanner_checks.injection_check."""

    def test_module_imports(self):
        """Verify injection_check.py imports cleanly."""
        mod = importlib.import_module("tools.web_scanner_checks.injection_check")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class InjectionCheck is available."""
        mod = importlib.import_module("tools.web_scanner_checks.injection_check")
        assert hasattr(mod, "InjectionCheck")
        assert callable(mod.InjectionCheck)

    def test_function_run_check_exists(self):
        """Verify function run_check is exported."""
        mod = importlib.import_module("tools.web_scanner_checks.injection_check")
        assert hasattr(mod, "run_check")
        assert callable(mod.run_check)
