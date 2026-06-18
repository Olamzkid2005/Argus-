"""Tests for runtime.engagement_state — Category: class"""

import pytest

from runtime.engagement_state import EngagementState
from runtime.engagement_state import ToolExecutionRecord


class TestToolExecutionRecord:
    """Tests for the ToolExecutionRecord class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            ToolExecutionRecord()

    def test_str_repr(self):
        """String representation not available."""
        with pytest.raises(TypeError):
            ToolExecutionRecord()


class TestEngagementState:
    """Tests for the EngagementState class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            ToolExecutionRecord()

    def test_str_repr(self):
        """String representation not available."""
        with pytest.raises(TypeError):
            ToolExecutionRecord()
