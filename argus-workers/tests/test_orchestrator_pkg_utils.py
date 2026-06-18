"""Smoke tests for orchestrator_pkg/utils.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for orchestrator_pkg.utils."""

    def test_module_imports(self):
        """Verify utils.py imports cleanly."""
        mod = importlib.import_module("orchestrator_pkg.utils")
        assert mod is not None

    def test_function_get_wordlist_path_exists(self):
        """Verify function get_wordlist_path is exported."""
        mod = importlib.import_module("orchestrator_pkg.utils")
        assert hasattr(mod, "get_wordlist_path")
        assert callable(mod.get_wordlist_path)

    def test_function_get_nuclei_templates_path_exists(self):
        """Verify function get_nuclei_templates_path is exported."""
        mod = importlib.import_module("orchestrator_pkg.utils")
        assert hasattr(mod, "get_nuclei_templates_path")
        assert callable(mod.get_nuclei_templates_path)

    def test_function_tool_timeout_exists(self):
        """Verify function tool_timeout is exported."""
        mod = importlib.import_module("orchestrator_pkg.utils")
        assert hasattr(mod, "tool_timeout")
        assert callable(mod.tool_timeout)
