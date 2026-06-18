"""Smoke tests for tools/web_scanner_checks/payloads/lfi_payloads.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.web_scanner_checks.payloads.lfi_payloads."""

    def test_module_imports(self):
        """Verify lfi_payloads.py imports cleanly."""
        mod = importlib.import_module("tools.web_scanner_checks.payloads.lfi_payloads")
        assert mod is not None

    def test_function_get_lfi_payloads_exists(self):
        """Verify function get_lfi_payloads is exported."""
        mod = importlib.import_module("tools.web_scanner_checks.payloads.lfi_payloads")
        assert hasattr(mod, "get_lfi_payloads")
        assert callable(mod.get_lfi_payloads)
