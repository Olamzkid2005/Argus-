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

from unittest.mock import patch

import pytest

from config.llm_env import set_worker_llm_config
from llm_client import LLMClient

HANDOFF = {
    "provider": "openai-compatible",
    "providerID": "opencode-go",
    "model": "kimi-k2.7-code",
    "apiKey": "sk-driver-key-1234567890",
    "baseUrl": "https://opencode.ai/zen/go/v1",
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
