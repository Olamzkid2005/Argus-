"""Smoke tests for parsers/parsers/jwt_tool.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for parsers.parsers.jwt_tool."""

    def test_module_imports(self):
        """Verify jwt_tool.py imports cleanly."""
        mod = importlib.import_module("parsers.parsers.jwt_tool")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class JwtToolParser is available."""
        mod = importlib.import_module("parsers.parsers.jwt_tool")
        assert hasattr(mod, "JwtToolParser")
        assert callable(mod.JwtToolParser)
