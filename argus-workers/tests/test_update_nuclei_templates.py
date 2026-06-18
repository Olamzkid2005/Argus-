"""Smoke tests for tools/update_nuclei_templates.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.update_nuclei_templates."""

    def test_module_imports(self):
        """Verify update_nuclei_templates.py imports cleanly."""
        mod = importlib.import_module("tools.update_nuclei_templates")
        assert mod is not None

    def test_function_update_nuclei_templates_exists(self):
        """Verify function update_nuclei_templates is exported."""
        mod = importlib.import_module("tools.update_nuclei_templates")
        assert hasattr(mod, "update_nuclei_templates")
        assert callable(mod.update_nuclei_templates)

    def test_function_get_template_count_exists(self):
        """Verify function get_template_count is exported."""
        mod = importlib.import_module("tools.update_nuclei_templates")
        assert hasattr(mod, "get_template_count")
        assert callable(mod.get_template_count)
