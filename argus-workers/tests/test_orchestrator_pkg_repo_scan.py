"""Smoke tests for orchestrator_pkg/repo_scan.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for orchestrator_pkg.repo_scan."""

    def test_module_imports(self):
        """Verify repo_scan.py imports cleanly."""
        mod = importlib.import_module("orchestrator_pkg.repo_scan")
        assert mod is not None
