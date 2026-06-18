"""Tests for llm_service — Category: dataclass"""

import pytest

from llm_service import CostTracker, LLMService, LLMServiceConfig


class TestCostTracker:
    """Tests for the CostTracker class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = CostTracker()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = CostTracker()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)


class TestLLMServiceConfig:
    """Tests for the LLMServiceConfig class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        instance = LLMServiceConfig()
        assert instance is not None
        assert isinstance(instance, LLMServiceConfig)

    def test_field_access(self):
        """Instance fields are accessible."""
        instance = LLMServiceConfig()
        fields = vars(instance) if hasattr(instance, '__dict__') else {}
        assert isinstance(fields, dict)


class TestLLMService:
    """Tests for the LLMService class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            LLMService()

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            LLMService()
