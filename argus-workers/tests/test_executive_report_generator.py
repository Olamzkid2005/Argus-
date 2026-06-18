"""Smoke tests for tools/executive_report_generator.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.executive_report_generator."""

    def test_module_imports(self):
        """Verify executive_report_generator.py imports cleanly."""
        mod = importlib.import_module("tools.executive_report_generator")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class ExecutiveReportGenerator is available."""
        mod = importlib.import_module("tools.executive_report_generator")
        assert hasattr(mod, "ExecutiveReportGenerator")
        assert callable(mod.ExecutiveReportGenerator)
