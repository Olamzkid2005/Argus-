"""Tests for runtime.decision_checkpoint — Category: dataclass"""

import pytest

from runtime.decision_checkpoint import DecisionCheckpoint, DecisionCheckpointRepository


class TestDecisionCheckpoint:
    """Tests for the DecisionCheckpoint class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            DecisionCheckpoint()


class TestDecisionCheckpointRepository:
    """Tests for the DecisionCheckpointRepository class."""

    def test_instantiation(self):
        """Default instantiation succeeds."""
        instance = DecisionCheckpointRepository()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = DecisionCheckpointRepository()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
