"""Smoke tests for tasks/replay.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tasks.replay."""

    def test_module_imports(self):
        """Verify replay.py imports cleanly."""
        mod = importlib.import_module("tasks.replay")
        assert mod is not None

    def test_function_replay_dlq_task_exists(self):
        """Verify function replay_dlq_task is exported."""
        mod = importlib.import_module("tasks.replay")
        assert hasattr(mod, "replay_dlq_task")
        assert callable(mod.replay_dlq_task)
