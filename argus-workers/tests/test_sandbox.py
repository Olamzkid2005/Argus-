"""Smoke tests for tool_core/sandbox.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tool_core.sandbox."""

    def test_module_imports(self):
        """Verify sandbox.py imports cleanly."""
        mod = importlib.import_module("tool_core.sandbox")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class AsyncToolRunner is available."""
        mod = importlib.import_module("tool_core.sandbox")
        assert hasattr(mod, "AsyncToolRunner")
        assert callable(mod.AsyncToolRunner)
