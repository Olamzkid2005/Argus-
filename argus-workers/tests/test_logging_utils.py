"""Smoke tests for utils/logging_utils.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for utils.logging_utils."""

    def test_module_imports(self):
        """Verify logging_utils.py imports cleanly."""
        mod = importlib.import_module("utils.logging_utils")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class SecretsRedactionFilter is available."""
        mod = importlib.import_module("utils.logging_utils")
        assert hasattr(mod, "SecretsRedactionFilter")
        assert callable(mod.SecretsRedactionFilter)
