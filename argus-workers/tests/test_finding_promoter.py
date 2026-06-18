"""Smoke tests for tools/verification/finding_promoter.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.verification.finding_promoter."""

    def test_module_imports(self):
        """Verify finding_promoter.py imports cleanly."""
        mod = importlib.import_module("tools.verification.finding_promoter")
        assert mod is not None

    def test_function_promote_finding_exists(self):
        """Verify function promote_finding is exported."""
        mod = importlib.import_module("tools.verification.finding_promoter")
        assert hasattr(mod, "promote_finding")
        assert callable(mod.promote_finding)
