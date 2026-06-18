"""Smoke tests for tools/port_scanner.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.port_scanner."""

    def test_module_imports(self):
        """Verify port_scanner.py imports cleanly."""
        mod = importlib.import_module("tools.port_scanner")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class OpenPort is available."""
        mod = importlib.import_module("tools.port_scanner")
        assert hasattr(mod, "OpenPort")
        assert callable(mod.OpenPort)

    def test_function_get_recommended_templates_exists(self):
        """Verify function get_recommended_templates is exported."""
        mod = importlib.import_module("tools.port_scanner")
        assert hasattr(mod, "get_recommended_templates")
        assert callable(mod.get_recommended_templates)
