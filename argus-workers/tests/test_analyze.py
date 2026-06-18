"""Smoke tests for tasks/analyze.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tasks.analyze."""

    def test_module_imports(self):
        """Verify analyze.py imports cleanly."""
        mod = importlib.import_module("tasks.analyze")
        assert mod is not None

    def test_function_run_analysis_exists(self):
        """Verify function run_analysis is exported."""
        mod = importlib.import_module("tasks.analyze")
        assert hasattr(mod, "run_analysis")
        assert callable(mod.run_analysis)
