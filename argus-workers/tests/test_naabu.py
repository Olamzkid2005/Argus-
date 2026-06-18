"""Smoke tests for parsers/parsers/naabu.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for parsers.parsers.naabu."""

    def test_module_imports(self):
        """Verify naabu.py imports cleanly."""
        mod = importlib.import_module("parsers.parsers.naabu")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class NaabuParser is available."""
        mod = importlib.import_module("parsers.parsers.naabu")
        assert hasattr(mod, "NaabuParser")
        assert callable(mod.NaabuParser)
