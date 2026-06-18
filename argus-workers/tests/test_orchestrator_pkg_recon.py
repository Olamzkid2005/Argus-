"""Smoke tests for orchestrator_pkg/recon.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for orchestrator_pkg.recon."""

    def test_module_imports(self):
        """Verify recon.py imports cleanly."""
        mod = importlib.import_module("orchestrator_pkg.recon")
        assert mod is not None

    def test_function_execute_recon_tools_exists(self):
        """Verify function execute_recon_tools is exported."""
        mod = importlib.import_module("orchestrator_pkg.recon")
        assert hasattr(mod, "execute_recon_tools")
        assert callable(mod.execute_recon_tools)

    def test_function_summarize_recon_findings_exists(self):
        """Verify function summarize_recon_findings is exported."""
        mod = importlib.import_module("orchestrator_pkg.recon")
        assert hasattr(mod, "summarize_recon_findings")
        assert callable(mod.summarize_recon_findings)
