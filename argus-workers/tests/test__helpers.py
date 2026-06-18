"""Smoke tests for tools/web_scanner_checks/_helpers.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.web_scanner_checks._helpers."""

    def test_module_imports(self):
        """Verify _helpers.py imports cleanly."""
        mod = importlib.import_module("tools.web_scanner_checks._helpers")
        assert mod is not None
