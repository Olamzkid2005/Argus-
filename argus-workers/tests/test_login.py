"""Smoke tests for tools/login.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.login."""

    def test_module_imports(self):
        """Verify login.py imports cleanly."""
        mod = importlib.import_module("tools.login")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class LoginTool is available."""
        mod = importlib.import_module("tools.login")
        assert hasattr(mod, "LoginTool")
        assert callable(mod.LoginTool)
