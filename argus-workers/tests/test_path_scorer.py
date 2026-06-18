"""Smoke tests for tools/attack_paths/path_scorer.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.attack_paths.path_scorer."""

    def test_module_imports(self):
        """Verify path_scorer.py imports cleanly."""
        mod = importlib.import_module("tools.attack_paths.path_scorer")
        assert mod is not None

    def test_function_score_path_exists(self):
        """Verify function score_path is exported."""
        mod = importlib.import_module("tools.attack_paths.path_scorer")
        assert hasattr(mod, "score_path")
        assert callable(mod.score_path)

    def test_function_rank_paths_exists(self):
        """Verify function rank_paths is exported."""
        mod = importlib.import_module("tools.attack_paths.path_scorer")
        assert hasattr(mod, "rank_paths")
        assert callable(mod.rank_paths)
