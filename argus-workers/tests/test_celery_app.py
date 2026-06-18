"""Smoke tests for celery_app.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for celery_app."""

    def test_module_imports(self):
        """Verify celery_app.py imports cleanly."""
        mod = importlib.import_module("celery_app")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class BaseTask is available."""
        mod = importlib.import_module("celery_app")
        assert hasattr(mod, "BaseTask")
        assert callable(mod.BaseTask)

    def test_function_setup_logging_exists(self):
        """Verify function setup_logging is exported."""
        mod = importlib.import_module("celery_app")
        assert hasattr(mod, "setup_logging")
        assert callable(mod.setup_logging)

    def test_function_ping_task_exists(self):
        """Verify function ping_task is exported."""
        mod = importlib.import_module("celery_app")
        assert hasattr(mod, "ping_task")
        assert callable(mod.ping_task)
