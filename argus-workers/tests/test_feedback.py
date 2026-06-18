"""Tests for models.feedback — Category: dataclass"""

import pytest

from models.feedback import FeedbackLearningLoop, FindingFeedback


class TestFindingFeedback:
    """Tests for the FindingFeedback class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            FindingFeedback()

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            FindingFeedback()


class TestFeedbackLearningLoop:
    """Tests for the FeedbackLearningLoop class."""

    def test_instantiation(self):
        """Default instantiation succeeds."""
        instance = FeedbackLearningLoop()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = FeedbackLearningLoop()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
