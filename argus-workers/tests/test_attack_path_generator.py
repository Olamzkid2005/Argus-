"""Smoke tests for tools/attack_path_generator.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.attack_path_generator."""

    def test_module_imports(self):
        """Verify attack_path_generator.py imports cleanly."""
        mod = importlib.import_module("tools.attack_path_generator")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class AttackPathGenerator is available."""
        mod = importlib.import_module("tools.attack_path_generator")
        assert hasattr(mod, "AttackPathGenerator")
        assert callable(mod.AttackPathGenerator)
