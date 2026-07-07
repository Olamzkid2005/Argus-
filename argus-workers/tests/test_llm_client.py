"""Tests for llm_client.py — LLMClient, LLMResponse, LLMUnavailableError."""

import os
from unittest.mock import patch

from llm_client import (
    LLMClient,
    LLMResponse,
    LLMUnavailableError,
    load_llm_setting,
)


class TestLLMResponse:
    def test_default_construction(self):
        resp = LLMResponse(text="hello")
        assert resp.text == "hello"
        assert resp.input_tokens == 0
        assert resp.output_tokens == 0
        assert resp.cost_usd == 0.0

    def test_full_construction(self):
        resp = LLMResponse(
            text="response", input_tokens=10, output_tokens=20, cost_usd=0.001
        )
        assert resp.text == "response"
        assert resp.input_tokens == 10
        assert resp.output_tokens == 20
        assert resp.cost_usd == 0.001


class TestLLMUnavailableError:
    def test_is_exception(self):
        err = LLMUnavailableError("test error")
        assert isinstance(err, Exception)
        assert str(err) == "test error"


class TestLLMClientInit:
    def test_defaults_no_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            client = LLMClient()
            assert client.provider == "openai"
            assert client.model == "gpt-4o-mini"
            assert client.api_key is None
            assert client.is_available() is False

    def test_explicit_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            client = LLMClient(api_key="sk-test-12345")
            assert client.api_key == "sk-test-12345"
            assert client.is_available() is True

    def test_api_key_from_env(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-env-abc"}, clear=True):
            client = LLMClient()
            assert client.api_key == "sk-env-abc"

    def test_api_key_llm_env(self):
        with patch.dict(os.environ, {"LLM_API_KEY": "sk-llm-key"}, clear=True):
            client = LLMClient()
            assert client.api_key == "sk-llm-key"

    def test_explicit_provider_and_model(self):
        client = LLMClient(
            provider="generic", model="gemini-2.0-flash", api_key="test-key"
        )
        assert client.provider == "generic"
        assert client.model == "gemini-2.0-flash"

    def test_openrouter_auto_detect(self):
        """sk-or- prefix should set provider to generic with OpenRouter URL."""
        client = LLMClient(api_key="sk-or-v1-test123")
        assert client.provider == "generic"
        assert "openrouter.ai" in client.api_url

    def test_gemini_auto_detect(self):
        """AIzaSy prefix should set provider to generic with Gemini URL."""
        client = LLMClient(api_key="AIzaSyTestKey12345")
        assert client.provider == "generic"
        assert "generativelanguage.googleapis.com" in client.api_url
        assert client.model == "gemini-2.0-flash"

    def test_gemini_aq_format(self):
        """AQ. prefix should also auto-detect as Gemini."""
        client = LLMClient(api_key="AQ.test-key-value-here")
        assert client.provider == "generic"
        assert "generativelanguage.googleapis.com" in client.api_url


class TestLLMClientCircuitBreaker:
    def test_initial_state_closed(self):
        client = LLMClient(api_key="sk-test-key-12345")
        assert client.is_available() is True

    def test_is_available_false_when_circuit_open(self):
        client = LLMClient(api_key="sk-test-key-12345")
        # Must exceed _circuit_threshold (5) for the circuit to be open
        client._circuit_failures = 5
        client._circuit_open_until = 9999999999.0
        assert client.is_available() is False

    def test_is_available_resets_after_cooldown(self):
        client = LLMClient(api_key="sk-test-key-12345")
        client._circuit_failures = 2
        client._circuit_open_until = 0.0  # expired
        assert client.is_available() is True
        # is_available() does NOT reset _circuit_failures — the reset happens
        # in chat()/chat_sync()/chat_async() on the actual probe call (H5 fix
        # for proper half-open circuit breaker semantics).
        assert client._circuit_failures == 2


class TestLLMClientRateLimit:
    def test_rate_limit_blocks(self, monkeypatch):
        client = LLMClient(api_key="sk-test")
        # Fill the in-process rate limiter with recent timestamps
        client._rate_limit_max = 2
        client._request_timestamps = [9999999999.0, 9999999999.1]
        # Should sleep because we're at the limit
        with patch("llm_client.time.sleep") as mock_sleep:
            client._check_rate_limit()
            mock_sleep.assert_called_once()

    def test_rate_limit_allows_under_limit(self):
        client = LLMClient(api_key="sk-test")
        client._rate_limit_max = 60
        client._request_timestamps = []
        with patch("llm_client.time.sleep") as mock_sleep:
            client._check_rate_limit()
            mock_sleep.assert_not_called()

    def test_rate_limit_empty_timestamps(self):
        client = LLMClient(api_key="sk-test")
        with patch("llm_client.time.sleep") as mock_sleep:
            client._check_rate_limit()
            mock_sleep.assert_not_called()


class TestLoadLLMSetting:
    def test_no_redis_url_returns_default(self):
        with patch.dict(os.environ, {}, clear=True):
            result = load_llm_setting("llm_review_enabled", default="false")
            assert result == "false"

    def test_redis_unavailable_returns_default(self):
        with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379"}):
            with patch("redis.from_url", side_effect=Exception("Connection refused")):
                result = load_llm_setting("llm_review_enabled", default="true")
                assert result == "true"
