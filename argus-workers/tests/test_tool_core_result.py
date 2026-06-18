"""Smoke tests for tool_core/result.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tool_core.result."""

    def test_module_imports(self):
        """Verify result.py imports cleanly."""
        mod = importlib.import_module("tool_core.result")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class ToolStatus is available."""
        mod = importlib.import_module("tool_core.result")
        assert hasattr(mod, "ToolStatus")
        assert callable(mod.ToolStatus)
