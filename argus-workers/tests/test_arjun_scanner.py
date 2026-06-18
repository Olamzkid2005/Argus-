"""Smoke tests for tools/arjun_scanner.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.arjun_scanner."""

    def test_module_imports(self):
        """Verify arjun_scanner.py imports cleanly."""
        mod = importlib.import_module("tools.arjun_scanner")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class ArjunScanner is available."""
        mod = importlib.import_module("tools.arjun_scanner")
        assert hasattr(mod, "ArjunScanner")
        assert callable(mod.ArjunScanner)
