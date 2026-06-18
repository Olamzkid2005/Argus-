"""Smoke tests for tasks/bugbounty.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tasks.bugbounty."""

    def test_module_imports(self):
        """Verify bugbounty.py imports cleanly."""
        mod = importlib.import_module("tasks.bugbounty")
        assert mod is not None

    def test_function_generate_bugbounty_report_exists(self):
        """Verify function generate_bugbounty_report is exported."""
        mod = importlib.import_module("tasks.bugbounty")
        assert hasattr(mod, "generate_bugbounty_report")
        assert callable(mod.generate_bugbounty_report)
