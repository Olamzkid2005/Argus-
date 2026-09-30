"""The worker must use the model the planner resolved for the run.

Argus has two LLM consumers: the TypeScript planner (which owns OpenCode's
provider registry and therefore knows which providers the operator configured)
and the Python worker that selects tools. Resolving independently let them
disagree — one run planned on OpenCode's provider while tool selection ran on
whatever key the surrounding shell happened to export.

The planner now resolves once and passes the concrete endpoint to the worker at
``agent_init``. These tests pin that handoff: it must beat the worker's own
``.env``, and the handoff key's prefix must not re-route the request to a
different provider (the ``sk-or-`` auto-detection used to do exactly that).
"""

import asyncio
import time
from unittest.mock import patch

import pytest

from config.llm_env import set_worker_llm_config
from exceptions import LLMUnavailableError
from llm_client import LLMClient, LLMResponse
from opencode_server_client import OpencodeServerError

HANDOFF = {
    "provider": "openai-compatible",
    "providerID": "opencode-go",
    "model": "kimi-k2.7-code",
    "apiKey": "sk-driver-key-1234567890",
    "baseUrl": "https://opencode.ai/zen/go/v1",
}

#: The second transport: no endpoint, no key — just the local OpenCode server
#: that is already running (docs/DEMO-READINESS-PLAN.md, blocker B9).
SERVER_HANDOFF = {
    "provider": "opencode-server",
    "providerID": "opencode",
    "modelID": "nemotron-3-ultra-free",
    "baseUrl": "http://127.0.0.1:4096",
    "directory": "/Users/mac/Documents/Argus-",
}


@pytest.fixture
def no_db_or_redis():
    """Isolate resolution to env + handoff so no DB/Redis is required."""
    with (
        patch.object(LLMClient, "_load_key_from_db", return_value=None),
        patch.object(LLMClient, "_load_key_from_redis", return_value=None),
    ):
        yield


@pytest.fixture(autouse=True)
def clear_run_config():
    yield
    set_worker_llm_config(None)


class TestWorkerAdoptsPlannerModel:
    def test_run_config_supplies_provider_model_url_and_key(self, no_db_or_redis):
        set_worker_llm_config(HANDOFF)

        client = LLMClient()

        assert client.provider == "generic"
        assert client.model == "kimi-k2.7-code"
        assert client.api_url == "https://opencode.ai/zen/go/v1/chat/completions"
        assert client.api_key == "sk-driver-key-1234567890"
        assert client.is_available() is True

    def test_run_config_beats_the_workers_own_env(self, no_db_or_redis, monkeypatch):
        # This is the split that made one run use two different models: Argus's
        # own .env named a Gemini model while the planner had chosen OpenCode's.
        monkeypatch.setenv("LLM_MODEL", "gemini-3.1-flash-lite")
        monkeypatch.setenv("LLM_API_KEY", "google-key")
        monkeypatch.setenv(
            "LLM_API_URL",
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        )
        set_worker_llm_config(HANDOFF)

        client = LLMClient()

        assert client.model == "kimi-k2.7-code"
        assert client.api_url == "https://opencode.ai/zen/go/v1/chat/completions"
        assert client.api_key == "sk-driver-key-1234567890"

    def test_handoff_key_prefix_does_not_reroute_the_request(self, no_db_or_redis):
        # An OpenRouter-shaped key used to force the OpenRouter URL. With the
        # endpoint declared by the planner, the prefix must be ignored.
        set_worker_llm_config({**HANDOFF, "apiKey": "sk-or-v1-driver-key"})

        client = LLMClient()

        assert client.api_url == "https://opencode.ai/zen/go/v1/chat/completions"
        assert client.model == "kimi-k2.7-code"

    def test_ambient_provider_key_is_still_ignored(self, no_db_or_redis, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-harness-leak")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
        set_worker_llm_config(HANDOFF)

        client = LLMClient()

        assert client.api_key == "sk-driver-key-1234567890"
        assert client.api_url == "https://opencode.ai/zen/go/v1/chat/completions"

    def test_explicit_arguments_still_win(self, no_db_or_redis):
        set_worker_llm_config(HANDOFF)

        client = LLMClient(
            provider="openai",
            model="explicit-model",
            api_key="explicit-key-1234567890",
            api_url="https://explicit.test/v1/chat/completions",
        )

        assert client.provider == "openai"
        assert client.model == "explicit-model"
        assert client.api_key == "explicit-key-1234567890"
        assert client.api_url == "https://explicit.test/v1/chat/completions"


class TestOpencodeServerHandoff:
    """The worker asks a local OpenCode server to make the call.

    OpenCode's own gateways refuse direct calls from this source tree, so the
    planner hands down the address of the server it spawned. These tests pin
    that the worker routes the call through it rather than trying to POST to a
    gateway of its own — and that a provider refusal is not retried, because a
    free-tier call costs 30-95s of quota.
    """

    def _client(self, monkeypatch, **overrides) -> LLMClient:
        # LLM_API_KEY is Argus's own variable and may legitimately be set in a
        # worker's shell; it must not turn the server transport into a direct
        # call or change what is available.
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        set_worker_llm_config({**SERVER_HANDOFF, **overrides})
        return LLMClient()

    def test_server_handoff_is_adopted_without_a_key(self, no_db_or_redis, monkeypatch):
        client = self._client(monkeypatch)

        assert client.provider == "opencode-server"
        assert client.model == "nemotron-3-ultra-free"
        assert not client.api_key
        assert client.api_url == ""
        # Available even without a key: OpenCode holds the credential.
        assert client.is_available() is True

    def test_no_credential_lookup_is_attempted(self, monkeypatch):
        # The server transport needs no key, so the worker must not query the
        # database or Redis looking for one. It used to, and logged an un-scoped
        # "loading API key from database" warning on a correctly configured run.
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        set_worker_llm_config(SERVER_HANDOFF)

        with (
            patch.object(LLMClient, "_load_key_from_db") as from_db,
            patch.object(LLMClient, "_load_key_from_redis") as from_redis,
        ):
            client = LLMClient(redis_url="redis://127.0.0.1:6379/0")

        from_db.assert_not_called()
        from_redis.assert_not_called()
        assert not client.api_key

    def test_own_key_cannot_reroute_the_server_transport(self, no_db_or_redis, monkeypatch):
        # An sk-or- key used to force the OpenRouter URL; a handoff that names a
        # transport must not be rewritten into a direct call to someone else.
        monkeypatch.setenv("LLM_API_KEY", "sk-or-v1-own-key")
        set_worker_llm_config(SERVER_HANDOFF)

        client = LLMClient()

        assert client.provider == "opencode-server"
        assert client.api_url == ""

    def test_call_is_made_through_the_server_client(self, no_db_or_redis, monkeypatch):
        client = self._client(monkeypatch)
        expected = LLMResponse(text="{\"tool\": \"nuclei\"}", input_tokens=5, output_tokens=7)

        with patch("opencode_server_client.OpencodeServerClient") as factory:
            factory.return_value.chat.return_value = expected
            result = client.chat_sync([{"role": "user", "content": "pick a tool"}])

        assert result is expected
        assert factory.call_args.kwargs == {
            "base_url": "http://127.0.0.1:4096",
            "model": "nemotron-3-ultra-free",
            "provider_id": "opencode",
            "directory": "/Users/mac/Documents/Argus-",
            # A free-tier call takes 30-95s; the direct transports' 30s default
            # would abort calls that are still working.
            "timeout": 180,
        }
        assert factory.return_value.chat.call_args.args[0] == [
            {"role": "user", "content": "pick a tool"}
        ]

    def test_async_call_is_made_through_the_server_client(self, no_db_or_redis, monkeypatch):
        client = self._client(monkeypatch)
        expected = LLMResponse(text="ok")

        with patch("opencode_server_client.OpencodeServerClient") as factory:
            factory.return_value.chat.return_value = expected
            result = asyncio.run(
                client.chat_async([{"role": "user", "content": "pick a tool"}])
            )

        assert result is expected
        assert factory.return_value.chat.call_count == 1

    def test_a_provider_refusal_is_not_retried(self, no_db_or_redis, monkeypatch):
        client = self._client(monkeypatch)

        with patch("opencode_server_client.OpencodeServerClient") as factory:
            factory.return_value.chat.side_effect = OpencodeServerError(
                "free tier can only be used from within OpenCode", retryable=False
            )
            with pytest.raises(LLMUnavailableError) as excinfo:
                client.chat_sync([{"role": "user", "content": "pick a tool"}])

        assert factory.return_value.chat.call_count == 1
        assert "free tier" in str(excinfo.value)
        # A config/provider error must not wedge the circuit for healthy work.
        assert client._circuit_failures == 0

    def test_a_transient_failure_is_retried_then_succeeds(self, no_db_or_redis, monkeypatch):
        client = self._client(monkeypatch)
        expected = LLMResponse(text="ok")

        with patch("opencode_server_client.OpencodeServerClient") as factory, patch.object(
            LLMClient, "_backoff_delay", return_value=0.0
        ):
            factory.return_value.chat.side_effect = [
                OpencodeServerError("server hiccup", retryable=True),
                expected,
            ]
            result = client.chat_sync([{"role": "user", "content": "pick a tool"}])

        assert result is expected
        assert factory.return_value.chat.call_count == 2
        assert client._circuit_failures == 0

    def test_retries_are_exhausted_before_giving_up(self, no_db_or_redis, monkeypatch):
        client = self._client(monkeypatch)
        client.max_retries = 2

        with patch("opencode_server_client.OpencodeServerClient") as factory, patch.object(
            LLMClient, "_backoff_delay", return_value=0.0
        ):
            factory.return_value.chat.side_effect = OpencodeServerError(
                "server hiccup", retryable=True
            )
            with pytest.raises(LLMUnavailableError) as excinfo:
                client.chat_sync([{"role": "user", "content": "pick a tool"}])

        assert factory.return_value.chat.call_count == 3
        assert "after 3 attempts" in str(excinfo.value)

    def test_availability_follows_the_circuit_breaker(self, no_db_or_redis, monkeypatch):
        client = self._client(monkeypatch)

        client._circuit_failures = client._circuit_threshold
        client._circuit_open_until = time.time() + 60

        assert client.is_available() is False


class TestWithoutHandoff:
    """Runs the driver did not start (CLI, celery) keep working as before."""

    def test_own_env_is_used_when_no_run_config(self, no_db_or_redis, monkeypatch):
        monkeypatch.setenv("LLM_MODEL", "gemini-3.1-flash-lite")
        monkeypatch.setenv("LLM_API_KEY", "google-key-1234567890")
        monkeypatch.setenv(
            "LLM_API_URL",
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        )

        client = LLMClient()

        assert client.model == "gemini-3.1-flash-lite"
        assert client.api_key == "google-key-1234567890"
        assert (
            client.api_url
            == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
        )

    def test_prefix_autodetect_still_applies_without_an_explicit_endpoint(
        self, no_db_or_redis, monkeypatch
    ):
        # Companion to the handoff test above: the prefix logic itself is intact,
        # it is only skipped when an endpoint was declared explicitly.
        monkeypatch.setenv("LLM_API_KEY", "sk-or-v1-own-key")

        client = LLMClient()

        assert client.api_url == "https://openrouter.ai/api/v1/chat/completions"

    def test_clearing_the_run_config_restores_env_resolution(self, no_db_or_redis, monkeypatch):
        monkeypatch.setenv("LLM_MODEL", "gemini-3.1-flash-lite")
        set_worker_llm_config(HANDOFF)
        assert LLMClient().model == "kimi-k2.7-code"

        set_worker_llm_config(None)
        assert LLMClient().model == "gemini-3.1-flash-lite"
