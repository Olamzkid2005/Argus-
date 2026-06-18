"""Smoke tests for tools/attack_surface_mapper.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.attack_surface_mapper."""

    def test_module_imports(self):
        """Verify attack_surface_mapper.py imports cleanly."""
        mod = importlib.import_module("tools.attack_surface_mapper")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class AttackSurfaceMapper is available."""
        mod = importlib.import_module("tools.attack_surface_mapper")
        assert hasattr(mod, "AttackSurfaceMapper")
        assert callable(mod.AttackSurfaceMapper)
