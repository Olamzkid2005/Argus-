"""Smoke tests for parsers/parsers/commix.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for parsers.parsers.commix."""

    def test_module_imports(self):
        """Verify commix.py imports cleanly."""
        mod = importlib.import_module("parsers.parsers.commix")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class CommixParser is available."""
        mod = importlib.import_module("parsers.parsers.commix")
        assert hasattr(mod, "CommixParser")
        assert callable(mod.CommixParser)
