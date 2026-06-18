"""Smoke tests for tasks/report.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tasks.report."""

    def test_module_imports(self):
        """Verify report.py imports cleanly."""
        mod = importlib.import_module("tasks.report")
        assert mod is not None
