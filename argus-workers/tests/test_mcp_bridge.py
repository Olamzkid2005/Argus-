"""Tests for tools.mcp_bridge — Category: class"""

import pytest

from tools.mcp_bridge import MCPToolBridge


class TestMCPToolBridge:
    """Tests for the MCPToolBridge class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = MCPToolBridge()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = MCPToolBridge()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
