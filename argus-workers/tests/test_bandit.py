"""Smoke tests for parsers/parsers/bandit.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for parsers.parsers.bandit."""

    def test_module_imports(self):
        """Verify bandit.py imports cleanly."""
        mod = importlib.import_module("parsers.parsers.bandit")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class BanditParser is available."""
        mod = importlib.import_module("parsers.parsers.bandit")
        assert hasattr(mod, "BanditParser")
        assert callable(mod.BanditParser)
