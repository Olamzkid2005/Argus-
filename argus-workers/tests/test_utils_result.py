"""Smoke tests for utils/result.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for utils.result."""

    def test_module_imports(self):
        """Verify result.py imports cleanly."""
        mod = importlib.import_module("utils.result")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class Ok is available."""
        mod = importlib.import_module("utils.result")
        assert hasattr(mod, "Ok")
        assert callable(mod.Ok)
