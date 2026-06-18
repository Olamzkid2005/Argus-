"""Smoke tests for tools/infrastructure_security_analyzer.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.infrastructure_security_analyzer."""

    def test_module_imports(self):
        """Verify infrastructure_security_analyzer.py imports cleanly."""
        mod = importlib.import_module("tools.infrastructure_security_analyzer")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class InfrastructureSecurityAnalyzer is available."""
        mod = importlib.import_module("tools.infrastructure_security_analyzer")
        assert hasattr(mod, "InfrastructureSecurityAnalyzer")
        assert callable(mod.InfrastructureSecurityAnalyzer)
