"""Smoke tests for tools/web_scanner_checks/payloads/xss_payloads.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.web_scanner_checks.payloads.xss_payloads."""

    def test_module_imports(self):
        """Verify xss_payloads.py imports cleanly."""
        mod = importlib.import_module("tools.web_scanner_checks.payloads.xss_payloads")
        assert mod is not None

    def test_function_get_xss_payloads_exists(self):
        """Verify function get_xss_payloads is exported."""
        mod = importlib.import_module("tools.web_scanner_checks.payloads.xss_payloads")
        assert hasattr(mod, "get_xss_payloads")
        assert callable(mod.get_xss_payloads)
