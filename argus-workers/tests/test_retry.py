"""Smoke tests for utils/retry.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for utils.retry."""

    def test_module_imports(self):
        """Verify retry.py imports cleanly."""
        mod = importlib.import_module("utils.retry")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class RetryExhaustedError is available."""
        mod = importlib.import_module("utils.retry")
        assert hasattr(mod, "RetryExhaustedError")
        assert callable(mod.RetryExhaustedError)

    def test_function_retry_exists(self):
        """Verify function retry is exported."""
        mod = importlib.import_module("utils.retry")
        assert hasattr(mod, "retry")
        assert callable(mod.retry)

    def test_function_retry_function_exists(self):
        """Verify function retry_function is exported."""
        mod = importlib.import_module("utils.retry")
        assert hasattr(mod, "retry_function")
        assert callable(mod.retry_function)
