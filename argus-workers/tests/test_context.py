"""Smoke tests for tools/context.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.context."""

    def test_module_imports(self):
        """Verify context.py imports cleanly."""
        mod = importlib.import_module("tools.context")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class ParserProtocol is available."""
        mod = importlib.import_module("tools.context")
        assert hasattr(mod, "ParserProtocol")
        assert callable(mod.ParserProtocol)
