"""Tests for tasks.utils — Category: class"""

import pytest

from tasks.utils import LlmCostTracker


class TestLlmCostTracker:
    """Tests for the LlmCostTracker class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            LlmCostTracker()

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            LlmCostTracker()
            str(LlmCostTracker())
