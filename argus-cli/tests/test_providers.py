"""
Tests for provider resolution.

Verifies model shorthand parsing and provider selection.
"""

import pytest

from argus_cli.core.providers import resolve_provider


class TestResolveProvider:
    """Test cases for resolve_provider()."""

    def test_openai_gpt_family(self):
        provider, model = resolve_provider("gpt-5")
        assert provider == "openai"
        assert model == "gpt-5"

    def test_openai_o_family(self):
        provider, model = resolve_provider("o3")
        assert provider == "openai"
        assert model == "o3"

    def test_anthropic_claude(self):
        provider, model = resolve_provider("claude-sonnet-4")
        assert provider == "anthropic"
        assert model == "claude-sonnet-4"

    def test_gemini(self):
        provider, model = resolve_provider("gemini-2.5-pro")
        assert provider == "gemini"
        assert model == "gemini-2.5-pro"

    def test_ollama_explicit(self):
        provider, model = resolve_provider("ollama:qwen3")
        assert provider == "ollama"
        assert model == "qwen3"

    def test_ollama_shorthand_qwen(self):
        provider, model = resolve_provider("qwen3")
        assert provider == "ollama"
        assert model == "qwen3"

    def test_ollama_shorthand_llama(self):
        provider, model = resolve_provider("llama3.3")
        assert provider == "ollama"
        assert model == "llama3.3"

    def test_ollama_shorthand_deepseek(self):
        provider, model = resolve_provider("deepseek-r1")
        assert provider == "ollama"
        assert model == "deepseek-r1"

    def test_unknown_fallback(self):
        provider, model = resolve_provider("some-random-model")
        assert provider == "openai"  # default fallback
        assert model == "some-random-model"
