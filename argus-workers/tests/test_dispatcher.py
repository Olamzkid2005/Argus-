"""Smoke tests for tool_core/parser/dispatcher.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tool_core.parser.dispatcher."""

    def test_module_imports(self):
        """Verify dispatcher.py imports cleanly."""
        mod = importlib.import_module("tool_core.parser.dispatcher")
        assert mod is not None

    def test_function_dispatch_exists(self):
        """Verify function dispatch is exported."""
        mod = importlib.import_module("tool_core.parser.dispatcher")
        assert hasattr(mod, "dispatch")
        assert callable(mod.dispatch)

    def test_function_has_parser_exists(self):
        """Verify function has_parser is exported."""
        mod = importlib.import_module("tool_core.parser.dispatcher")
        assert hasattr(mod, "has_parser")
        assert callable(mod.has_parser)
