"""
Tests for LLM Payload Generator.
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from tools.llm_payload_generator import LLMPayloadGenerator, PayloadCache


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client."""
    client = MagicMock()
    client.is_available.return_value = True
    client.model = "gpt-4o-mini"
    return client


@pytest.fixture
def generator(mock_llm_client):
    """Create LLMPayloadGenerator with mock client."""
    return LLMPayloadGenerator(llm_client=mock_llm_client)


class TestPayloadCache:
    """Test suite for PayloadCache."""

    def test_set_and_get(self):
        cache = PayloadCache(ttl=3600)
        cache.set("test", ["payload1", "payload2"])
        result = cache.get("test")
        assert result == ["payload1", "payload2"]

    def test_miss_returns_none(self):
        cache = PayloadCache(ttl=3600)
        assert cache.get("nonexistent") is None

    def test_expiry(self):
        cache = PayloadCache(ttl=-1)  # Already expired
        cache.set("test", ["payload"])
        assert cache.get("test") is None

    def test_clear(self):
        cache = PayloadCache(ttl=3600)
        cache.set("test", ["payload"])
        cache.clear()
        assert cache.get("test") is None


class TestLLMPayloadGenerator:
    """Test suite for LLMPayloadGenerator."""

    def test_generate_sync_returns_payloads(self, generator, mock_llm_client):
        """Test basic payload generation."""
        mock_llm_client.chat_sync.return_value = json.dumps([
            "<script>alert('LLM_TEST')</script>",
            "\"><img src=x onerror=alert('LLM_TEST')>",
            "<svg onload=alert('LLM_TEST')>",
        ])

        payloads = generator.generate_sync(
            vuln_class="XSS",
            param_name="q",
            response_snippet='<html><body><input name="q" value="test"></body></html>',
        )

        assert len(payloads) > 0
        assert len(payloads) <= generator.max_payloads
        assert all(isinstance(p, str) for p in payloads)

    def test_generate_sync_llm_unavailable(self, mock_llm_client):
        """Test graceful degradation when LLM is unavailable."""
        mock_llm_client.is_available.return_value = False
        gen = LLMPayloadGenerator(llm_client=mock_llm_client)

        payloads = gen.generate_sync(
            vuln_class="XSS",
            param_name="q",
        )

        assert payloads == []

    def test_generate_sync_llm_error(self, generator, mock_llm_client):
        """Test graceful degradation when LLM call fails."""
        mock_llm_client.chat_sync.side_effect = Exception("LLM error")

        payloads = generator.generate_sync(
            vuln_class="XSS",
            param_name="q",
        )

        assert payloads == []

    def test_cache_used_on_second_call(self, generator, mock_llm_client):
        """Test that cached payloads are returned without calling LLM again."""
        mock_llm_client.chat_sync.return_value = json.dumps([
            "<script>alert(1)</script>",
        ])

        # First call — should call LLM
        first = generator.generate_sync("XSS", "q", "<html>test</html>")
        assert mock_llm_client.chat_sync.call_count == 1

        # Second call with same params — should use cache
        second = generator.generate_sync("XSS", "q", "<html>test</html>")
        assert mock_llm_client.chat_sync.call_count == 1  # Not incremented
        assert first == second

    def test_different_params_different_cache(self, generator, mock_llm_client):
        """Test that different params produce different cache keys."""
        mock_llm_client.chat_sync.return_value = json.dumps(["payload"])

        generator.generate_sync("XSS", "q", "<html>test</html>")
        generator.generate_sync("XSS", "id", "<html>test</html>")

        assert mock_llm_client.chat_sync.call_count == 2

    def test_detect_reflection_context_html(self, generator):
        """Test context detection for HTML body."""
        context = generator._detect_reflection_context("q", '<html><body><p>test q value</p></body></html>')
        assert context == "html_body"

    def test_detect_reflection_context_script(self, generator):
        """Test context detection for script context."""
        context = generator._detect_reflection_context(
            "name",
            '<html><script>var name = "test";</script></html>'
        )
        # Should detect script tag containing 'name'
        assert context is not None

    def test_parse_payloads_json(self, generator):
        """Test parsing of JSON array of payloads."""
        raw = '["<script>alert(1)</script>", "<img src=x onerror=alert(1)>"]'
        payloads = generator._parse_payloads(raw)
        assert len(payloads) == 2
        assert "<script>alert(1)</script>" in payloads

    def test_parse_payloads_markdown_json(self, generator):
        """Test parsing of JSON inside markdown code block."""
        raw = '```json\n["<script>alert(1)</script>"]\n```'
        payloads = generator._parse_payloads(raw)
        assert len(payloads) == 1

    def test_parse_payloads_invalid(self, generator):
        """Test parsing of invalid response returns gracefully."""
        payloads = generator._parse_payloads("not json at all")
        assert isinstance(payloads, list)

    def test_is_available_disabled(self, mock_llm_client):
        """Test is_available returns False when disabled."""
        with patch('tools.llm_payload_generator.LLM_PAYLOAD_GENERATION_ENABLED', False):
            gen = LLMPayloadGenerator(llm_client=mock_llm_client)
            assert gen.is_available() is False

    def test_generate_sync_max_payloads(self, generator, mock_llm_client):
        """Test that returned payloads are capped at max_payloads."""
        mock_llm_client.chat_sync.return_value = json.dumps([
            "p1", "p2", "p3", "p4", "p5",
        ])

        payloads = generator.generate_sync(
            vuln_class="XSS",
            param_name="q",
        )

        assert len(payloads) <= generator.max_payloads
