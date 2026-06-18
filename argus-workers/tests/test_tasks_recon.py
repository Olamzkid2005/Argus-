"""Smoke tests for tasks/recon.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tasks.recon."""

    def test_module_imports(self):
        """Verify recon.py imports cleanly."""
        mod = importlib.import_module("tasks.recon")
        assert mod is not None

    def test_function_run_recon_exists(self):
        """Verify function run_recon is exported."""
        mod = importlib.import_module("tasks.recon")
        assert hasattr(mod, "run_recon")
        assert callable(mod.run_recon)

    def test_function_expand_recon_exists(self):
        """Verify function expand_recon is exported."""
        mod = importlib.import_module("tasks.recon")
        assert hasattr(mod, "expand_recon")
        assert callable(mod.expand_recon)
