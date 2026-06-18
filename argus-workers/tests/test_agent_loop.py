"""Tests for agent_loop — Category: module"""

import pytest


class TestModule:
    """Tests for agent_loop."""

    def test_import(self):
        """Module imports cleanly."""
        import importlib
        mod = importlib.import_module("agent_loop")
        assert mod is not None

    def test_has_public_api(self):
        """Module has public symbols."""
        import importlib
        mod = importlib.import_module("agent_loop")
        public = [x for x in dir(mod) if not x.startswith('_')]
        assert len(public) > 0
