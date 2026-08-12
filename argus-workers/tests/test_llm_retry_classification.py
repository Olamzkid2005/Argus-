"""Tests for retry classification and backoff in llm_client.

Verifies:
- 4xx client errors are NOT retried (raise immediately, no circuit trip)
- 429 / 5xx / network errors ARE retried with exponential backoff
- backoff includes jitter and honors Retry-After headers
"""

from unittest.mock import MagicMock, patch

import pytest

from exceptions import LLMUnavailableError
from llm_client import LLMClient


class _FakeResp:
    def __init__(self, status, headers=None):
        self.status_code = status
        self.headers = headers or {}


class _FakeHttpStatus(Exception):
    """httpx-style error: status lives on e.response.status_code."""

    def __init__(self, status, headers=None):
        self.response = _FakeResp(status, headers)
        super().__init__(f"status {status}")


class _FakeSdkStatus(Exception):
    """OpenAI-SDK-style error: status lives directly on the exception."""

    def __init__(self, status):
        self.status_code = status
        super().__init__(f"status {status}")


def _generic_client() -> LLMClient:
    """Provider=generic with an unknown-prefix key keeps the HTTP path active."""
    client = LLMClient(provider="generic", api_key="test-key-1234")
    client.api_url = "https://example.invalid/v1/chat/completions"
    client.max_retries = 2
    return client


def _fake_http_client(fake_post):
    fake_client = MagicMock()
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)
    fake_client.post = fake_post
    return fake_client


class TestIsRetryableError:
    def test_429_retryable(self):
        assert LLMClient._is_retryable_error(_FakeHttpStatus(429))

    def test_5xx_retryable(self):
        assert LLMClient._is_retryable_error(_FakeHttpStatus(503))
        assert LLMClient._is_retryable_error(_FakeHttpStatus(500))

    def test_4xx_not_retryable(self):
        assert not LLMClient._is_retryable_error(_FakeHttpStatus(401))
        assert not LLMClient._is_retryable_error(_FakeHttpStatus(400))
        assert not LLMClient._is_retryable_error(_FakeHttpStatus(403))

    def test_sdk_status_code_shape(self):
        assert LLMClient._is_retryable_error(_FakeSdkStatus(429))
        assert not LLMClient._is_retryable_error(_FakeSdkStatus(403))

    def test_network_errors_retryable(self):
        assert LLMClient._is_retryable_error(ConnectionError("refused"))
        assert LLMClient._is_retryable_error(TimeoutError("timed out"))
        assert LLMClient._is_retryable_error(OSError("socket closed"))

    def test_generic_errors_not_retryable(self):
        assert not LLMClient._is_retryable_error(ValueError("bad payload"))
        assert not LLMClient._is_retryable_error(RuntimeError("boom"))


class TestBackoffDelay:
    def test_exponential_plus_jitter(self):
        d0 = LLMClient._backoff_delay(0)
        d1 = LLMClient._backoff_delay(1)
        d2 = LLMClient._backoff_delay(2)
        assert 1.0 <= d0 < 1.5
        assert 2.0 <= d1 < 2.5
        assert 4.0 <= d2 < 4.5

    def test_honors_retry_after_header(self):
        e = _FakeHttpStatus(429, headers={"Retry-After": "5"})
        delay = LLMClient._backoff_delay(3, e)
        assert 4.9 <= delay <= 5.1

    def test_no_retry_after_uses_exponential(self):
        e = _FakeHttpStatus(429, headers={})
        delay = LLMClient._backoff_delay(2, e)
        assert 4.0 <= delay < 4.5

    def test_retry_after_capped_at_60s(self):
        e = _FakeHttpStatus(429, headers={"Retry-After": "120"})
        assert LLMClient._backoff_delay(0, e) <= 60.0


class TestRetryLoopClassification:
    def test_non_retryable_error_raises_immediately(self):
        """A 401 must not be retried and must not trip the circuit breaker."""
        client = _generic_client()
        calls = {"n": 0}

        def fake_post(*a, **k):
            calls["n"] += 1
            resp = MagicMock()
            resp.raise_for_status.side_effect = _FakeHttpStatus(401)
            return resp

        with patch("httpx.Client", return_value=_fake_http_client(fake_post)):
            with pytest.raises(LLMUnavailableError):
                client._call_llm_core_sync([{"role": "user", "content": "hi"}])

        assert calls["n"] == 1, "401 must not be retried"
        assert client._circuit_failures == 0, "config errors must not trip the breaker"

    def test_retryable_error_retries_with_backoff(self):
        """503 twice then success: 3 attempts, 2 sleeps, valid result."""
        client = _generic_client()
        calls = {"n": 0}
        sleeps = []

        def fake_post(*a, **k):
            calls["n"] += 1
            resp = MagicMock()
            if calls["n"] < 3:
                resp.raise_for_status.side_effect = _FakeHttpStatus(503)
                return resp
            resp.raise_for_status.return_value = None
            resp.json.return_value = {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
            return resp

        with patch("httpx.Client", return_value=_fake_http_client(fake_post)), patch(
            "llm_client.time.sleep", side_effect=lambda s: sleeps.append(s)
        ):
            result = client._call_llm_core_sync([{"role": "user", "content": "hi"}])

        assert calls["n"] == 3
        assert result.text == "ok"
        assert len(sleeps) == 2
        # backoff grows: first sleep < second sleep
        assert sleeps[0] < sleeps[1]

    def test_exhausted_retries_raise_unavailable(self):
        client = _generic_client()

        def fake_post(*a, **k):
            resp = MagicMock()
            resp.raise_for_status.side_effect = _FakeHttpStatus(503)
            return resp

        with patch("httpx.Client", return_value=_fake_http_client(fake_post)), patch(
            "llm_client.time.sleep"
        ):
            with pytest.raises(LLMUnavailableError):
                client._call_llm_core_sync([{"role": "user", "content": "hi"}])

        assert client._circuit_failures >= client._circuit_threshold
