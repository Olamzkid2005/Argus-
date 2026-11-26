"""Live OpenCode agent adapters (agent/delegation/opencode_agents.py).

No network, no server, no keys: the server client is faked. These tests pin
the adapter contracts — what is sent to the model and what the dispatcher
receives back — and the fail-closed behaviour on unusable replies.
"""

from __future__ import annotations

import pytest

from agent.delegation.opencode_agents import (
    OpencodeAgentsError,
    OpencodePlanGenerator,
    factory,
    opencode_bootstrapper,
    opencode_reasoner,
)
from llm_client import LLMResponse
from opencode_server_client import OpencodeServerError


class FakeServer:
    """Scripted stand-in for OpencodeServerClient.chat."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return LLMResponse(text=reply, input_tokens=10, output_tokens=5, cost_usd=0.0)


def _generator_request():
    return {
        "task_id": "t-1",
        "engagement_id": "e-1",
        "objective": "probe the login surface",
        "intent": {"id": "i-1", "objective": "probe the login surface"},
        "facts": [{"id": "f-1", "payload": {"summary": "login page exists"}}],
        "hints": [],
        "max_subtasks": 5,
    }


def test_generator_returns_model_drafts():
    drafts = [
        {"title": "Map login", "description": "enumerate the login surface"},
        {"title": "Probe login", "description": "try defaults", "depends_on": ["Map login"]},
    ]
    import json

    generator = OpencodePlanGenerator(FakeServer([json.dumps(drafts)]))
    assert generator.generate(_generator_request()) == drafts


def test_generator_refuses_non_json_reply():
    generator = OpencodePlanGenerator(FakeServer(["sure, here is a plan: ..."]))
    with pytest.raises(OpencodeAgentsError):
        generator.generate(_generator_request())


def test_generator_retries_retryable_failure_once():
    import json

    drafts = [{"title": "Map login", "description": "enumerate"}]
    server = FakeServer(
        [OpencodeServerError("empty reply", retryable=True), json.dumps(drafts)]
    )
    generator = OpencodePlanGenerator(server)
    assert generator.generate(_generator_request()) == drafts
    assert server.calls == 2


def test_generator_gives_up_on_refusal():
    server = FakeServer([OpencodeServerError("FreeTierError", retryable=False)])
    generator = OpencodePlanGenerator(server)
    with pytest.raises(OpencodeServerError):
        generator.generate(_generator_request())
    assert server.calls == 1


def _reason_job():
    return {
        "engagement_id": "e-1",
        "facts": [{"id": "f-1", "description": "login page exists"}],
        "open_intents": [],
        "max_intents": 5,
    }


def test_reasoner_passes_intents_through():
    import json

    payload = {"intents": [{"description": "probe login", "from": ["f-1"]}]}
    result = opencode_reasoner(_reason_job(), FakeServer([json.dumps(payload)]))
    assert result == {"accepted": True, "data": payload}


def test_reasoner_empty_object_means_noop():
    result = opencode_reasoner(_reason_job(), FakeServer(["{}"]))
    assert result == {"accepted": True, "data": {}}


def test_reasoner_passes_complete_through():
    import json

    payload = {"complete": {"description": "goal proven", "from": ["f-1"]}}
    result = opencode_reasoner(_reason_job(), FakeServer([json.dumps(payload)]))
    assert result == {"accepted": True, "data": payload}


def test_reasoner_rejects_non_object_reply():
    import json

    with pytest.raises(OpencodeAgentsError):
        opencode_reasoner(_reason_job(), FakeServer([json.dumps(["not", "an", "object"])]))


def test_bootstrapper_execute_returns_fact_and_complete():
    import json

    payload = {
        "fact": {"description": "engagement may probe login"},
        "complete": {"description": "surface mapped and verified"},
    }
    result = opencode_bootstrapper({"engagement_id": "e-1"}, FakeServer([json.dumps(payload)]))
    assert result == {"accepted": True, "data": payload}


def test_bootstrapper_conclude_returns_fact_only():
    import json

    payload = {"fact": {"description": "origin fact"}}
    result = opencode_bootstrapper(
        {"engagement_id": "e-1"}, FakeServer([json.dumps(payload)]), conclude=True
    )
    assert result == {"accepted": True, "data": payload}


def test_factory_needs_provider_and_model(monkeypatch):
    monkeypatch.delenv("ARGUS_OPENCODE_PROVIDER_ID", raising=False)
    monkeypatch.delenv("ARGUS_OPENCODE_MODEL_ID", raising=False)
    with pytest.raises(OpencodeAgentsError):
        factory()


def test_factory_returns_all_three_adapters(monkeypatch):
    monkeypatch.setenv("ARGUS_OPENCODE_PROVIDER_ID", "opencode")
    monkeypatch.setenv("ARGUS_OPENCODE_MODEL_ID", "test-model")
    parts = factory()
    assert set(parts) == {"generator", "reasoner", "bootstrapper"}
    assert hasattr(parts["generator"], "generate")
    assert callable(parts["reasoner"])
    assert callable(parts["bootstrapper"])


def test_factory_plugs_into_integrated_runner_from_env(monkeypatch):
    from control_plane.integrated import integrated_runner_from_env

    monkeypatch.setenv("ARGUS_OPENCODE_PROVIDER_ID", "opencode")
    monkeypatch.setenv("ARGUS_OPENCODE_MODEL_ID", "test-model")
    monkeypatch.setenv(
        "ARGUS_INTEGRATED_TASK_AGENTS",
        "agent.delegation.opencode_agents:factory",
    )
    runner = integrated_runner_from_env()
    assert runner is not None
    assert callable(runner._reasoner)
    assert callable(runner._bootstrapper)


def test_factory_uses_run_level_config_first(monkeypatch):
    from config import llm_env

    monkeypatch.setenv("ARGUS_OPENCODE_PROVIDER_ID", "env-provider")
    monkeypatch.setenv("ARGUS_OPENCODE_MODEL_ID", "env-model")
    config = llm_env.WorkerLlmConfig(
        provider="opencode-server",
        model="run-model",
        provider_id="run-provider",
        model_id="run-model",
        base_url="http://127.0.0.1:9999",
    )
    monkeypatch.setattr(llm_env, "_run_config", config)
    parts = factory()
    assert parts["generator"]._client.provider_id == "run-provider"
    assert parts["generator"]._client.model == "run-model"
