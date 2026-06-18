"""Smoke tests for parsers/parsers/govulncheck.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for parsers.parsers.govulncheck."""

    def test_module_imports(self):
        """Verify govulncheck.py imports cleanly."""
        mod = importlib.import_module("parsers.parsers.govulncheck")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class GovulncheckParser is available."""
        mod = importlib.import_module("parsers.parsers.govulncheck")
        assert hasattr(mod, "GovulncheckParser")
        assert callable(mod.GovulncheckParser)
