"""Smoke tests for tools/websocket_scanner.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for tools.websocket_scanner."""

    def test_module_imports(self):
        """Verify websocket_scanner.py imports cleanly."""
        mod = importlib.import_module("tools.websocket_scanner")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class WebSocketScanner is available."""
        mod = importlib.import_module("tools.websocket_scanner")
        assert hasattr(mod, "WebSocketScanner")
        assert callable(mod.WebSocketScanner)
