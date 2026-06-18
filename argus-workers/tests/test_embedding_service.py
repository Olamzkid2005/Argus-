"""Smoke tests for database/services/embedding_service.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for database.services.embedding_service."""

    def test_module_imports(self):
        """Verify embedding_service.py imports cleanly."""
        mod = importlib.import_module("database.services.embedding_service")
        assert mod is not None

    def test_main_class_exists(self):
        """Verify key class EmbeddingService is available."""
        mod = importlib.import_module("database.services.embedding_service")
        assert hasattr(mod, "EmbeddingService")
        assert callable(mod.EmbeddingService)
