"""Smoke tests for tools/correlation/priority_ranker.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.correlation.priority_ranker."""

    def test_module_imports(self):
        """Verify priority_ranker.py imports cleanly."""
        mod = importlib.import_module("tools.correlation.priority_ranker")
        assert mod is not None

    def test_function_rank_findings_exists(self):
        """Verify function rank_findings is exported."""
        mod = importlib.import_module("tools.correlation.priority_ranker")
        assert hasattr(mod, "rank_findings")
        assert callable(mod.rank_findings)
