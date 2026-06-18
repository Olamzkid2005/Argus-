"""Smoke tests for tools/browser_scanner.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.browser_scanner."""

    def test_module_imports(self):
        """Verify browser_scanner.py imports cleanly."""
        mod = importlib.import_module("tools.browser_scanner")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class BrowserScanner is available."""
        mod = importlib.import_module("tools.browser_scanner")
        assert hasattr(mod, "BrowserScanner")
        assert callable(mod.BrowserScanner)

    def test_function_scan_exists(self):
        """Verify function scan is exported."""
        mod = importlib.import_module("tools.browser_scanner")
        assert hasattr(mod, "scan")
        assert callable(mod.scan)

    def test_function_is_spa_target_exists(self):
        """Verify function is_spa_target is exported."""
        mod = importlib.import_module("tools.browser_scanner")
        assert hasattr(mod, "is_spa_target")
        assert callable(mod.is_spa_target)
