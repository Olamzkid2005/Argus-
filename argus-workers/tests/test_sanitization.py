"""Smoke tests for utils/sanitization.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for utils.sanitization."""

    def test_module_imports(self):
        """Verify sanitization.py imports cleanly."""
        mod = importlib.import_module("utils.sanitization")
        assert mod is not None
