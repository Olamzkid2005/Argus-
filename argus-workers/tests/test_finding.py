"""Smoke tests for models/finding.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for models.finding."""

    def test_module_imports(self):
        """Verify finding.py imports cleanly."""
        mod = importlib.import_module("models.finding")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class Severity is available."""
        mod = importlib.import_module("models.finding")
        assert hasattr(mod, "Severity")
        assert callable(mod.Severity)
