"""Tests for agent.agent_config — Category: module"""



class TestModule:
    """Tests for agent.agent_config."""

    def test_import(self):
        """Module imports cleanly."""
        import importlib
        mod = importlib.import_module("agent.agent_config")
        assert mod is not None

    def test_has_public_api(self):
        """Module has public symbols."""
        import importlib
        mod = importlib.import_module("agent.agent_config")
        public = [x for x in dir(mod) if not x.startswith('_')]
        assert len(public) > 0
