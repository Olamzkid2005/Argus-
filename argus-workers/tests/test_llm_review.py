"""Smoke tests for tasks/llm_review.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tasks.llm_review."""

    def test_module_imports(self):
        """Verify llm_review.py imports cleanly."""
        mod = importlib.import_module("tasks.llm_review")
        assert mod is not None

    def test_function_run_llm_review_exists(self):
        """Verify function run_llm_review is exported."""
        mod = importlib.import_module("tasks.llm_review")
        assert hasattr(mod, "run_llm_review")
        assert callable(mod.run_llm_review)
