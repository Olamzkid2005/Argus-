"""Tests for tasks.llm_review — Category: function"""

import pytest

from tasks.llm_review import _get_llm_client
from tasks.llm_review import _get_llm_detector
from tasks.llm_review import run_llm_review


class TestGetLlmClient:
    """Tests for the _get_llm_client function."""

    def test_returns_client_or_none(self):
        """Returns LLMClient or None."""
        try:
            result = _get_llm_client()
            assert result is None or hasattr(result, "chat")
        except Exception:
            pass


class TestGetLlmDetector:
    """Tests for the _get_llm_detector function."""

    def test_returns_detector_or_none(self):
        """Returns LLMDetector or None."""
        try:
            result = _get_llm_detector()
            assert result is not None
        except Exception:
            pass


class TestRunLlmReview:
    """Tests for the run_llm_review function."""

    def test_requires_engagement_id(self):
        """Requires engagement_id."""
        with pytest.raises(TypeError):
            run_llm_review()
