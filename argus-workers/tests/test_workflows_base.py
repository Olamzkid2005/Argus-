"""Smoke tests for runtime/workflows/base.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for runtime.workflows.base."""

    def test_module_imports(self):
        """Verify base.py imports cleanly."""
        mod = importlib.import_module("runtime.workflows.base")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class WorkflowContext is available."""
        mod = importlib.import_module("runtime.workflows.base")
        assert hasattr(mod, "WorkflowContext")
        assert callable(mod.WorkflowContext)
