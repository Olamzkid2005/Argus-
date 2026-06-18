"""Smoke tests for parsers/parsers/npm_audit.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for parsers.parsers.npm_audit."""

    def test_module_imports(self):
        """Verify npm_audit.py imports cleanly."""
        mod = importlib.import_module("parsers.parsers.npm_audit")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class NpmAuditParser is available."""
        mod = importlib.import_module("parsers.parsers.npm_audit")
        assert hasattr(mod, "NpmAuditParser")
        assert callable(mod.NpmAuditParser)
