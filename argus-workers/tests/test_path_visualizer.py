"""Smoke tests for tools/attack_paths/path_visualizer.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.attack_paths.path_visualizer."""

    def test_module_imports(self):
        """Verify path_visualizer.py imports cleanly."""
        mod = importlib.import_module("tools.attack_paths.path_visualizer")
        assert mod is not None

    def test_function_render_text_path_exists(self):
        """Verify function render_text_path is exported."""
        mod = importlib.import_module("tools.attack_paths.path_visualizer")
        assert hasattr(mod, "render_text_path")
        assert callable(mod.render_text_path)

    def test_function_render_all_paths_exists(self):
        """Verify function render_all_paths is exported."""
        mod = importlib.import_module("tools.attack_paths.path_visualizer")
        assert hasattr(mod, "render_all_paths")
        assert callable(mod.render_all_paths)

    def test_function_render_mermaid_exists(self):
        """Verify function render_mermaid is exported."""
        mod = importlib.import_module("tools.attack_paths.path_visualizer")
        assert hasattr(mod, "render_mermaid")
        assert callable(mod.render_mermaid)
