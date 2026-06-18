"""Smoke tests for parsers/parsers/katana.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for parsers.parsers.katana."""

    def test_module_imports(self):
        """Verify katana.py imports cleanly."""
        mod = importlib.import_module("parsers.parsers.katana")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class KatanaParser is available."""
        mod = importlib.import_module("parsers.parsers.katana")
        assert hasattr(mod, "KatanaParser")
        assert callable(mod.KatanaParser)
