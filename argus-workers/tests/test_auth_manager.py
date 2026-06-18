"""Smoke tests for tools/auth_manager.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.auth_manager."""

    def test_module_imports(self):
        """Verify auth_manager.py imports cleanly."""
        mod = importlib.import_module("tools.auth_manager")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class AuthError is available."""
        mod = importlib.import_module("tools.auth_manager")
        assert hasattr(mod, "AuthError")
        assert callable(mod.AuthError)
