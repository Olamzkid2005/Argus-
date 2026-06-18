"""Smoke tests for tasks/posture.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tasks.posture."""

    def test_module_imports(self):
        """Verify posture.py imports cleanly."""
        mod = importlib.import_module("tasks.posture")
        assert mod is not None

    def test_function_recompute_posture_exists(self):
        """Verify function recompute_posture is exported."""
        mod = importlib.import_module("tasks.posture")
        assert hasattr(mod, "recompute_posture")
        assert callable(mod.recompute_posture)
