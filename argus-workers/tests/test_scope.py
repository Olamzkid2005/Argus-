"""Smoke tests for tool_core/validators/scope.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tool_core.validators.scope."""

    def test_module_imports(self):
        """Verify scope.py imports cleanly."""
        mod = importlib.import_module("tool_core.validators.scope")
        assert mod is not None
