"""Smoke tests for tasks/scheduled.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tasks.scheduled."""

    def test_module_imports(self):
        """Verify scheduled.py imports cleanly."""
        mod = importlib.import_module("tasks.scheduled")
        assert mod is not None

    def test_function_run_due_scans_exists(self):
        """Verify function run_due_scans is exported."""
        mod = importlib.import_module("tasks.scheduled")
        assert hasattr(mod, "run_due_scans")
        assert callable(mod.run_due_scans)
