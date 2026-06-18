"""Tests for tool_core.validators.scope — Category: module"""



class TestModule:
    """Tests for tool_core.validators.scope."""

    def test_import(self):
        """Module imports cleanly."""
        import importlib
        mod = importlib.import_module("tool_core.validators.scope")
        assert mod is not None

    def test_has_public_api(self):
        """Module has public symbols."""
        import importlib
        mod = importlib.import_module("tool_core.validators.scope")
        public = [x for x in dir(mod) if not x.startswith('_')]
        assert len(public) > 0
