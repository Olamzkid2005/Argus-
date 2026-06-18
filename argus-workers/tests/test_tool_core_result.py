"""Tests for tool_core.result — Category: dataclass"""

import pytest

from tool_core.result import ToolStatus, UnifiedToolResult


class TestToolStatus:
    """Tests for the ToolStatus enum."""

    def test_members_exist(self):
        """Enum has expected members."""
        members = list(ToolStatus)
        assert len(members) > 0
        for member in members:
            assert member.name
            assert member.value is not None


class TestUnifiedToolResult:
    """Tests for the UnifiedToolResult class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            UnifiedToolResult()

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            UnifiedToolResult()
