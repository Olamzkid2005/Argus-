"""Smoke tests for tools/secure_code_intelligence_engine.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.secure_code_intelligence_engine."""

    def test_module_imports(self):
        """Verify secure_code_intelligence_engine.py imports cleanly."""
        mod = importlib.import_module("tools.secure_code_intelligence_engine")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class SecureCodeIntelligenceEngine is available."""
        mod = importlib.import_module("tools.secure_code_intelligence_engine")
        assert hasattr(mod, "SecureCodeIntelligenceEngine")
        assert callable(mod.SecureCodeIntelligenceEngine)
