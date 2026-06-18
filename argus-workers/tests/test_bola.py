"""Smoke tests for runtime/workflows/bola.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for runtime.workflows.bola."""

    def test_module_imports(self):
        """Verify bola.py imports cleanly."""
        mod = importlib.import_module("runtime.workflows.bola")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class BolaWorkflow is available."""
        mod = importlib.import_module("runtime.workflows.bola")
        assert hasattr(mod, "BolaWorkflow")
        assert callable(mod.BolaWorkflow)
