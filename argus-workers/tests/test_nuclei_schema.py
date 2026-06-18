"""Smoke tests for parsers/schemas/nuclei_schema.py

Phase 1 — Filename Coverage
Verifies the module can be imported without errors.
"""

from __future__ import annotations

import importlib
import pytest


class TestSmoke:
    """Smoke tests for parsers.schemas.nuclei_schema."""

    def test_module_imports(self):
        """Verify nuclei_schema.py imports cleanly."""
        mod = importlib.import_module("parsers.schemas.nuclei_schema")
        assert mod is not None

    def test_function_validate_nuclei_finding_exists(self):
        """Verify function validate_nuclei_finding is exported."""
        mod = importlib.import_module("parsers.schemas.nuclei_schema")
        assert hasattr(mod, "validate_nuclei_finding")
        assert callable(mod.validate_nuclei_finding)
