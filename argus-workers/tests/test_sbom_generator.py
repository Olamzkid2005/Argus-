"""Smoke tests for tools/sbom_generator.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.sbom_generator."""

    def test_module_imports(self):
        """Verify sbom_generator.py imports cleanly."""
        mod = importlib.import_module("tools.sbom_generator")
        assert mod is not None

    def test_function_generate_sbom_from_findings_exists(self):
        """Verify function generate_sbom_from_findings is exported."""
        mod = importlib.import_module("tools.sbom_generator")
        assert hasattr(mod, "generate_sbom_from_findings")
        assert callable(mod.generate_sbom_from_findings)
