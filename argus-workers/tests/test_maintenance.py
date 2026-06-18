"""Smoke tests for tasks/maintenance.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tasks.maintenance."""

    def test_module_imports(self):
        """Verify maintenance.py imports cleanly."""
        mod = importlib.import_module("tasks.maintenance")
        assert mod is not None
