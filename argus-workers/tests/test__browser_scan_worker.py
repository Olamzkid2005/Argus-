"""Smoke tests for tools/_browser_scan_worker.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools._browser_scan_worker."""

    def test_module_imports(self):
        """Verify _browser_scan_worker.py imports cleanly."""
        mod = importlib.import_module("tools._browser_scan_worker")
        assert mod is not None

    def test_function_scan_exists(self):
        """Verify function scan is exported."""
        mod = importlib.import_module("tools._browser_scan_worker")
        assert hasattr(mod, "scan")
        assert callable(mod.scan)
