"""Smoke tests for tasks/utils.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tasks.utils."""

    def test_module_imports(self):
        """Verify utils.py imports cleanly."""
        mod = importlib.import_module("tasks.utils")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class LlmCostTracker is available."""
        mod = importlib.import_module("tasks.utils")
        assert hasattr(mod, "LlmCostTracker")
        assert callable(mod.LlmCostTracker)
