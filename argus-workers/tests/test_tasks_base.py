"""Smoke tests for tasks/base.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tasks.base."""

    def test_module_imports(self):
        """Verify base.py imports cleanly."""
        mod = importlib.import_module("tasks.base")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class OperatorCanceled is available."""
        mod = importlib.import_module("tasks.base")
        assert hasattr(mod, "OperatorCanceled")
        assert callable(mod.OperatorCanceled)

    def test_function_task_context_exists(self):
        """Verify function task_context is exported."""
        mod = importlib.import_module("tasks.base")
        assert hasattr(mod, "task_context")
        assert callable(mod.task_context)

    def test_function_task_error_boundary_exists(self):
        """Verify function task_error_boundary is exported."""
        mod = importlib.import_module("tasks.base")
        assert hasattr(mod, "task_error_boundary")
        assert callable(mod.task_error_boundary)
