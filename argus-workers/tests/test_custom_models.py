"""Unified custom cyber-model registry (config/custom_models.py + wiring).

No network, no database: the registry is read from temp files and the
LLMClient assertions arrange a credential so no DB/Redis lookup fires.
"""

from __future__ import annotations

import json

import pytest

from config import custom_models
from config.custom_models import (
    CustomModelError,
    list_custom_models,
    load_registry,
    resolve_custom_model,
    resolve_custom_model_key,
)


def _write_registry(tmp_path, models):
    path = tmp_path / "custom_models.json"
    path.write_text(json.dumps({"models": models}), encoding="utf-8")
    return path


def _entry(**overrides):
    base = {
        "base_url": "http://localhost:11434/v1",
        "model": "white-rabbit",
        "api_key_env": None,
        "description": "local cyber model",
    }
    base.update(overrides)
    return base


def test_empty_models_loads_clean(tmp_path):
    assert load_registry(_write_registry(tmp_path, {})) == {}


def test_missing_file_loads_clean(tmp_path):
    assert load_registry(tmp_path / "absent.json") == {}


def test_valid_entry_parses(tmp_path):
    models = load_registry(_write_registry(tmp_path, {"lab": _entry()}))
    assert models["lab"].base_url == "http://localhost:11434/v1"
    assert models["lab"].model == "white-rabbit"
    assert models["lab"].api_key_env is None


def test_list_is_sorted(tmp_path):
    models = list_custom_models(
        _write_registry(tmp_path, {"zeta": _entry(), "alpha": _entry()})
    )
    assert [entry.name for entry in models] == ["alpha", "zeta"]


def test_invalid_json_raises(tmp_path):
    path = tmp_path / "custom_models.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(CustomModelError):
        load_registry(path)


@pytest.mark.parametrize(
    "entry",
    [
        {"model": "x", "api_key_env": None},  # no base_url
        {"base_url": "ftp://host/v1", "model": "x"},  # non-http scheme
        {"base_url": "http://host/v1"},  # no model
        {"base_url": "http://host/v1", "model": "x", "api_key_env": "has-dash"},
    ],
)
def test_malformed_entries_raise(tmp_path, entry):
    with pytest.raises(CustomModelError):
        load_registry(_write_registry(tmp_path, {"bad": entry}))


def test_resolve_returns_none_for_unknown(tmp_path):
    path = _write_registry(tmp_path, {"lab": _entry()})
    assert resolve_custom_model("nope", path) is None
    assert resolve_custom_model("", path) is None


def test_keyless_entry_uses_placeholder(tmp_path):
    entry = resolve_custom_model("lab", _write_registry(tmp_path, {"lab": _entry()}))
    assert resolve_custom_model_key(entry, environ={}) == "sk-no-key-required"


def test_named_env_key_resolves(tmp_path):
    entry = resolve_custom_model(
        "lab",
        _write_registry(tmp_path, {"lab": _entry(api_key_env="CYBER_KEY")}),
    )
    assert resolve_custom_model_key(entry, environ={"CYBER_KEY": " secret "}) == "secret"
    assert resolve_custom_model_key(entry, environ={}) is None


def test_shipped_registry_is_valid():
    assert isinstance(load_registry(), dict)


# --- LLMClient wiring --------------------------------------------------------


def _client(monkeypatch, name, registry_path):
    import llm_client

    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_URL", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setattr(
        custom_models, "default_registry_path", lambda: registry_path
    )
    assert llm_client.resolve_custom_model is not None  # wired import
    return llm_client.LLMClient(model=name)


def test_registry_entry_fills_endpoint_and_model(tmp_path, monkeypatch):
    path = _write_registry(tmp_path, {"lab": _entry()})
    client = _client(monkeypatch, "lab", path)
    assert client.model == "white-rabbit"
    assert client.api_url == "http://localhost:11434/v1/chat/completions"
    assert client.api_key == "sk-no-key-required"


def test_explicit_api_url_wins_over_registry(tmp_path, monkeypatch):
    import llm_client

    path = _write_registry(tmp_path, {"lab": _entry()})
    monkeypatch.setattr(custom_models, "default_registry_path", lambda: path)
    client = llm_client.LLMClient(
        model="lab", api_url="https://other.example/v1/chat/completions"
    )
    assert client.api_url == "https://other.example/v1/chat/completions"


def test_registry_key_env_used_when_set(tmp_path, monkeypatch):
    path = _write_registry(tmp_path, {"lab": _entry(api_key_env="CYBER_KEY")})
    monkeypatch.setenv("CYBER_KEY", "k-123")
    client = _client(monkeypatch, "lab", path)
    assert client.api_key == "k-123"


def test_unknown_name_leaves_normal_chain(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("LLM_API_KEY", "sk-own-key")
    path = _write_registry(tmp_path, {"lab": _entry()})
    import llm_client

    monkeypatch.setattr(custom_models, "default_registry_path", lambda: path)
    client = llm_client.LLMClient()
    assert client.model == "gpt-4o-mini"
    assert client.api_key == "sk-own-key"
