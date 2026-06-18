"""Smoke tests for job_schema.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for job_schema."""

    def test_module_imports(self):
        """Verify job_schema.py imports cleanly."""
        mod = importlib.import_module("job_schema")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class JobMessage is available."""
        mod = importlib.import_module("job_schema")
        assert hasattr(mod, "JobMessage")
        assert callable(mod.JobMessage)

    def test_function_build_task_args_exists(self):
        """Verify function build_task_args is exported."""
        mod = importlib.import_module("job_schema")
        assert hasattr(mod, "build_task_args")
        assert callable(mod.build_task_args)
