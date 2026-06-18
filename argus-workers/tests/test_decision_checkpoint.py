"""Tests for runtime.decision_checkpoint — Category: dataclass"""

import pytest

from runtime.decision_checkpoint import DecisionCheckpoint
from runtime.decision_checkpoint import DecisionCheckpointRepository


class TestDecisionCheckpoint:
    """Tests for the DecisionCheckpoint class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            DecisionCheckpoint()


class TestDecisionCheckpointRepository:
    """Tests for the DecisionCheckpointRepository class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            DecisionCheckpointRepository()

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            DecisionCheckpointRepository()
