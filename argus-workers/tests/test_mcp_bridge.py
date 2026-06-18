"""Tests for tools.mcp_bridge — Category: class"""

import pytest

from tools.mcp_bridge import MCPToolBridge


class TestMCPToolBridge:
    """Tests for the MCPToolBridge class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            MCPToolBridge()

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            MCPToolBridge()
