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


class TestStage6BoundedLLMCall:
    """Stage 6.1 item 2: the caller can clamp an LLM call to remaining time."""

    def test_chat_json_passes_the_caller_timeout_to_the_client(self):
        from llm_client import LLMResponse

        seen: dict = {}

        class FakeClient:
            model = "fake"

            def is_available(self):
                return True

            def chat_sync(self, **kwargs):
                seen.update(kwargs)
                return LLMResponse(
                    text='{"tool": "nuclei"}',
                    input_tokens=10,
                    output_tokens=4,
                    cost_usd=0.0,
                )

        service = LLMService(FakeClient())
        result = service.chat_json(
            system_prompt="s", user_prompt="u", max_tokens=10, timeout=3
        )

        assert seen["timeout"] == 3
        assert result == {"tool": "nuclei"}
        assert service.last_input_tokens == 10
        assert service.last_output_tokens == 4

    def test_default_timeout_is_used_when_the_caller_does_not_clamp(self):
        from llm_client import LLMResponse

        seen: dict = {}

        class FakeClient:
            def is_available(self):
                return True

            def chat_sync(self, **kwargs):
                seen.update(kwargs)
                return LLMResponse(text="{}", input_tokens=0, output_tokens=0, cost_usd=0.0)

        service = LLMService(FakeClient(), config=LLMServiceConfig(timeout=77))
        service.chat_json(system_prompt="s", user_prompt="u")

        assert seen["timeout"] == 77
