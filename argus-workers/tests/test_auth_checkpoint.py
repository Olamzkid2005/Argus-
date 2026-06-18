"""Smoke tests for agent/auth_checkpoint.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for agent.auth_checkpoint."""

    def test_module_imports(self):
        """Verify auth_checkpoint.py imports cleanly."""
        mod = importlib.import_module("agent.auth_checkpoint")
        assert mod is not None

    def test_function_save_auth_checkpoint_exists(self):
        """Verify function save_auth_checkpoint is exported."""
        mod = importlib.import_module("agent.auth_checkpoint")
        assert hasattr(mod, "save_auth_checkpoint")
        assert callable(mod.save_auth_checkpoint)

    def test_function_load_auth_checkpoint_exists(self):
        """Verify function load_auth_checkpoint is exported."""
        mod = importlib.import_module("agent.auth_checkpoint")
        assert hasattr(mod, "load_auth_checkpoint")
        assert callable(mod.load_auth_checkpoint)

    def test_function_clear_auth_checkpoint_exists(self):
        """Verify function clear_auth_checkpoint is exported."""
        mod = importlib.import_module("agent.auth_checkpoint")
        assert hasattr(mod, "clear_auth_checkpoint")
        assert callable(mod.clear_auth_checkpoint)
