"""Smoke tests for parsers/parsers/dalfox.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for parsers.parsers.dalfox."""

    def test_module_imports(self):
        """Verify dalfox.py imports cleanly."""
        mod = importlib.import_module("parsers.parsers.dalfox")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class DalfoxParser is available."""
        mod = importlib.import_module("parsers.parsers.dalfox")
        assert hasattr(mod, "DalfoxParser")
        assert callable(mod.DalfoxParser)
