"""Tests for the LLM credential resolution policy (config/llm_env.py).

These are the regression tests for the ambient-credential leak: the worker used
to resolve its key as ``OPENAI_API_KEY or LLM_API_KEY``, so a key exported by an
unrelated tool would silently become the provider Argus ran and billed.
"""

import pytest

from config.llm_env import (
    ALLOW_AMBIENT_ENV_VAR,
    AMBIENT_LLM_ENV_VARS,
    InvalidWorkerLlmConfig,
    ambient_ignored_note,
    ambient_llm_env_allowed,
    build_worker_llm_config,
    ignored_ambient_llm_env_vars,
    resolve_llm_api_key,
    set_worker_llm_config,
    worker_llm_config,
)


class TestAmbientPolicy:
    def test_allows_ambient_when_opted_in(self):
        assert ambient_llm_env_allowed({ALLOW_AMBIENT_ENV_VAR: "1"}) is True
        assert ambient_llm_env_allowed({ALLOW_AMBIENT_ENV_VAR: "true"}) is True
        assert ambient_llm_env_allowed({ALLOW_AMBIENT_ENV_VAR: "YES"}) is True

    def test_ambient_not_allowed_by_default(self):
        assert ambient_llm_env_allowed({}) is False
        assert ambient_llm_env_allowed({ALLOW_AMBIENT_ENV_VAR: "0"}) is False

    def test_ignored_vars_lists_set_ambient_keys(self):
        ignored = ignored_ambient_llm_env_vars(
            {"OPENAI_API_KEY": "sk-x", "OPENAI_BASE_URL": "https://example.test"}
        )
        assert ignored == ["OPENAI_API_KEY", "OPENAI_BASE_URL"]

    def test_ignored_vars_empty_when_opted_in(self):
        ignored = ignored_ambient_llm_env_vars(
            {ALLOW_AMBIENT_ENV_VAR: "1", "OPENAI_API_KEY": "sk-x"}
        )
        assert ignored == []

    def test_blank_ambient_values_are_not_configured(self):
        assert ignored_ambient_llm_env_vars({"OPENAI_API_KEY": "   "}) == []

    def test_ambient_list_covers_the_leak_sources(self):
        for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENCODE_API_KEY", "OPENAI_BASE_URL"):
            assert name in AMBIENT_LLM_ENV_VARS


class TestResolveLlmApiKey:
    def test_explicit_key_wins(self):
        env = {"LLM_API_KEY": "sk-own", "OPENAI_API_KEY": "sk-ambient"}
        assert resolve_llm_api_key("sk-explicit", env) == "sk-explicit"

    def test_own_key_preferred_over_ambient(self):
        env = {"LLM_API_KEY": "sk-own", "OPENAI_API_KEY": "sk-ambient"}
        assert resolve_llm_api_key(None, env) == "sk-own"

    def test_ambient_ignored_by_default(self):
        env = {"OPENAI_API_KEY": "sk-harness-key", "ANTHROPIC_API_KEY": "sk-ant"}
        assert resolve_llm_api_key(None, env) is None

    def test_ambient_used_when_opted_in(self):
        env = {ALLOW_AMBIENT_ENV_VAR: "1", "OPENAI_API_KEY": "sk-ambient"}
        assert resolve_llm_api_key(None, env) == "sk-ambient"

    def test_own_key_still_preferred_when_opted_in(self):
        env = {ALLOW_AMBIENT_ENV_VAR: "1", "LLM_API_KEY": "sk-own", "OPENAI_API_KEY": "sk-ambient"}
        assert resolve_llm_api_key(None, env) == "sk-own"

    def test_returns_none_when_nothing_configured(self):
        assert resolve_llm_api_key(None, {}) is None

    def test_blank_values_are_skipped(self):
        assert resolve_llm_api_key(None, {"LLM_API_KEY": "  "}) is None
        assert resolve_llm_api_key("   ", {"LLM_API_KEY": "sk-own"}) == "sk-own"


class TestAmbientIgnoredNote:
    def test_note_names_the_ignored_vars_and_the_opt_in(self):
        note = ambient_ignored_note({"OPENAI_API_KEY": "sk-x"})
        assert "OPENAI_API_KEY" in note
        assert ALLOW_AMBIENT_ENV_VAR in note

    def test_note_is_empty_when_nothing_ignored(self):
        assert ambient_ignored_note({}) == ""


_DriverLlmBlock = {
    "provider": "openai-compatible",
    "providerID": "opencode-go",
    "model": "kimi-k2.7-code",
    "apiKey": "driver-key",
    "baseUrl": "https://opencode.ai/zen/go/v1",
}


class TestWorkerLlmConfig:
    """The planner resolves the model; the worker must adopt that decision."""

    def teardown_method(self):
        set_worker_llm_config(None)

    def test_builds_an_openai_compatible_endpoint(self):
        config = build_worker_llm_config(_DriverLlmBlock)
        assert config.provider == "generic"
        assert config.model == "kimi-k2.7-code"
        assert config.api_key == "driver-key"
        assert config.api_url == "https://opencode.ai/zen/go/v1/chat/completions"
        assert config.provider_id == "opencode-go"
        assert config.source == "opencode-registry"

    def test_chat_completions_path_is_not_duplicated(self):
        config = build_worker_llm_config(
            {**_DriverLlmBlock, "baseUrl": "https://example.test/v1/chat/completions"}
        )
        assert config.api_url == "https://example.test/v1/chat/completions"

    def test_adopting_and_clearing_the_run_config(self):
        assert worker_llm_config() is None
        assert set_worker_llm_config(_DriverLlmBlock) is not None
        assert worker_llm_config() is not None
        assert set_worker_llm_config(None) is None
        assert worker_llm_config() is None

    @pytest.mark.parametrize(
        "payload",
        [
            None,
            "not-an-object",
            {**_DriverLlmBlock, "provider": "anthropic"},
            {**_DriverLlmBlock, "model": ""},
            {**_DriverLlmBlock, "apiKey": ""},
            {**_DriverLlmBlock, "baseUrl": ""},
            {**_DriverLlmBlock, "baseUrl": "ftp://example.test/v1"},
        ],
    )
    def test_rejects_unusable_blocks(self, payload):
        with pytest.raises(InvalidWorkerLlmConfig):
            build_worker_llm_config(payload)

    def test_malformed_block_does_not_replace_a_previous_one(self):
        set_worker_llm_config(_DriverLlmBlock)
        with pytest.raises(InvalidWorkerLlmConfig):
            set_worker_llm_config({"provider": "anthropic"})
        # The old config survives, so a bad handoff cannot leave the worker
        # pointing at a half-configured model.
        assert worker_llm_config() is not None
        assert worker_llm_config().model == "kimi-k2.7-code"
