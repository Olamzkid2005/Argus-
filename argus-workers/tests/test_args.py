"""Smoke tests for tool_core/validators/args.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tool_core.validators.args."""

    def test_module_imports(self):
        """Verify args.py imports cleanly."""
        mod = importlib.import_module("tool_core.validators.args")
        assert mod is not None

    def test_function_is_dangerous_exists(self):
        """Verify function is_dangerous is exported."""
        mod = importlib.import_module("tool_core.validators.args")
        assert hasattr(mod, "is_dangerous")
        assert callable(mod.is_dangerous)
