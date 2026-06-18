"""Tests for tools.tool_result — Category: module"""



class TestModule:
    """Tests for tools.tool_result."""

    def test_import(self):
        """Module imports cleanly."""
        import importlib
        mod = importlib.import_module("tools.tool_result")
        assert mod is not None

    def test_has_public_api(self):
        """Module has public symbols."""
        import importlib
        mod = importlib.import_module("tools.tool_result")
        public = [x for x in dir(mod) if not x.startswith('_')]
        assert len(public) > 0
