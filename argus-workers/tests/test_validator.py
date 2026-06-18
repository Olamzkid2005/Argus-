"""Smoke tests for custom_rules/validator.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for custom_rules.validator."""

    def test_module_imports(self):
        """Verify validator.py imports cleanly."""
        mod = importlib.import_module("custom_rules.validator")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class RuleValidationError is available."""
        mod = importlib.import_module("custom_rules.validator")
        assert hasattr(mod, "RuleValidationError")
        assert callable(mod.RuleValidationError)
