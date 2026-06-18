"""Smoke tests for runtime/workflows/steps.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for runtime.workflows.steps."""

    def test_module_imports(self):
        """Verify steps.py imports cleanly."""
        mod = importlib.import_module("runtime.workflows.steps")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class AuthenticateStep is available."""
        mod = importlib.import_module("runtime.workflows.steps")
        assert hasattr(mod, "AuthenticateStep")
        assert callable(mod.AuthenticateStep)
