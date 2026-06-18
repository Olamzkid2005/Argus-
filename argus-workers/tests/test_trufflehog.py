"""Smoke tests for parsers/parsers/trufflehog.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for parsers.parsers.trufflehog."""

    def test_module_imports(self):
        """Verify trufflehog.py imports cleanly."""
        mod = importlib.import_module("parsers.parsers.trufflehog")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class TrufflehogParser is available."""
        mod = importlib.import_module("parsers.parsers.trufflehog")
        assert hasattr(mod, "TrufflehogParser")
        assert callable(mod.TrufflehogParser)
