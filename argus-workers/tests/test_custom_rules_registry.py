"""Smoke tests for custom_rules/registry.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for custom_rules.registry."""

    def test_module_imports(self):
        """Verify registry.py imports cleanly."""
        mod = importlib.import_module("custom_rules.registry")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class RuleRegistry is available."""
        mod = importlib.import_module("custom_rules.registry")
        assert hasattr(mod, "RuleRegistry")
        assert callable(mod.RuleRegistry)
