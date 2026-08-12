"""Tests for JSON recovery in llm_service (fenced / prose-wrapped LLM output)."""

from unittest.mock import MagicMock

from llm_client import LLMResponse
from llm_service import LLMService


class TestExtractJson:
    """Unit tests for LLMService._extract_json recovery ladder."""

    def test_direct_json(self):
        assert LLMService._extract_json('{"a": 1}') == {"a": 1}

    def test_direct_json_array(self):
        assert LLMService._extract_json('[1, 2, 3]') == [1, 2, 3]

    def test_fenced_json_with_lang(self):
        text = 'Here is the result:\n```json\n{"a": 1}\n```\nHope that helps.'
        assert LLMService._extract_json(text) == {"a": 1}

    def test_fenced_json_without_lang(self):
        text = '```\n{"a": [1, 2]}\n```'
        assert LLMService._extract_json(text) == {"a": [1, 2]}

    def test_prose_wrapped(self):
        text = 'The plan is: {"tool": "nuclei", "args": ["-u", "http://x"]} — proceed.'
        assert LLMService._extract_json(text) == {
            "tool": "nuclei",
            "args": ["-u", "http://x"],
        }

    def test_skips_prose_braces_before_json(self):
        # The {note} brace is prose; the real JSON block follows it.
        text = 'See {note} the result: {"summary": "ok"}'
        assert LLMService._extract_json(text) == {"summary": "ok"}

    def test_braces_inside_strings_are_ignored(self):
        text = '{"a": "text with { brace and } close", "b": 2}'
        assert LLMService._extract_json(text) == {
            "a": "text with { brace and } close",
            "b": 2,
        }

    def test_returns_none_for_garbage(self):
        assert LLMService._extract_json("no json here at all") is None

    def test_returns_none_for_empty(self):
        assert LLMService._extract_json("") is None
        assert LLMService._extract_json(None) is None


class TestChatJsonRecovery:
    """chat_json should return recovered data instead of the fallback dict."""

    def _service_with(self, text: str) -> LLMService:
        client = MagicMock()
        client.is_available.return_value = True
        client.model = "test-model"
        client.chat_sync.return_value = LLMResponse(text=text)
        return LLMService(llm_client=client)

    def test_fenced_json_is_recovered(self):
        service = self._service_with(
            '```json\n{"executive_summary": "real analysis"}\n```'
        )
        parsed = service.chat_json("sys", "user")
        assert parsed.get("_fallback") is not True
        assert parsed["executive_summary"] == "real analysis"

    def test_prose_wrapped_json_is_recovered(self):
        service = self._service_with(
            'Analysis complete: {"executive_summary": "ok", "risk_level": "high"}'
        )
        parsed = service.chat_json("sys", "user")
        assert parsed.get("_fallback") is not True
        assert parsed["risk_level"] == "high"

    def test_garbage_still_falls_back(self):
        service = self._service_with("I cannot produce JSON today.")
        parsed = service.chat_json("sys", "user")
        assert parsed.get("_fallback") is True
        assert parsed.get("_error") is True
