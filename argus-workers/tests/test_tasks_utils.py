"""Tests for tasks.utils — Category: class"""

import pytest

from llm_service import CostTracker
from tasks.utils import LlmCostTracker


class TestLlmCostTracker:
    """Tests for the LlmCostTracker class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            LlmCostTracker()

    def test_exceeded_accepts_the_llm_service_estimate(self):
        """LLMService calls ``exceeded(cost)`` with the call's cost (M-v4-18).

        The alias used to take no argument, so wiring this tracker into
        LLMService made every call raise TypeError and fall back silently.
        """
        tracker = LlmCostTracker("eng-1", max_cost=1.0)

        assert tracker.exceeded() is False
        assert tracker.exceeded(0.5) is False
        assert tracker.exceeded(1.5) is True

    def test_exceeded_matches_the_cost_tracker_it_aliases(self):
        ours = LlmCostTracker("eng-1", max_cost=1.0)
        theirs = CostTracker(max_cost_usd=1.0)

        for estimate in (0.0, 0.5, 1.0, 1.5):
            assert ours.exceeded(estimate) == theirs.exceeded(estimate)

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            LlmCostTracker()
