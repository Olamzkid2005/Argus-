"""Smoke tests for tool_core/parser/parsers/nmap.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tool_core.parser.parsers.nmap."""

    def test_module_imports(self):
        """Verify nmap.py imports cleanly."""
        mod = importlib.import_module("tool_core.parser.parsers.nmap")
        assert mod is not None

    def test_function_parse_exists(self):
        """Verify function parse is exported."""
        mod = importlib.import_module("tool_core.parser.parsers.nmap")
        assert hasattr(mod, "parse")
        assert callable(mod.parse)
