"""Unified registry for custom OpenAI-compatible cyber models.

One entry in ``config/custom_models.json`` feeds both runtimes: the Python
workers resolve ``LLM_MODEL=<name>`` to the entry's endpoint, and the TUI
generates the matching ``opencode.json`` provider block from the same file
(see ``Argus-Tui/.../planner/custom-models.ts`` and
``docs/custom-cyber-models.md``).

Schema per entry::

    {
      "base_url": "http://localhost:11434/v1",   # required, http(s)
      "model": "whiterabbitneo",                  # required, model id at that endpoint
      "api_key_env": "CYBER_MODEL_API_KEY",       # optional; null = keyless local server
      "description": "..."                        # optional, shown by list commands
    }

``api_key_env: null`` means the endpoint needs no credential (local Ollama /
vLLM with ``--api-key`` unset). The worker then sends a placeholder key, which
OpenAI-compatible servers accept and ignore.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

REGISTRY_FILENAME = "custom_models.json"

#: Placeholder key for keyless local endpoints. OpenAI-compatible servers
#: (Ollama, vLLM) accept any non-empty bearer token and ignore it.
NO_KEY_PLACEHOLDER = "sk-no-key-required"


class CustomModelError(ValueError):
    """The registry file or an entry in it is unusable."""


@dataclass(frozen=True)
class CustomModel:
    name: str
    base_url: str
    model: str
    api_key_env: str | None
    description: str = ""


def chat_completions_url(base_url: str) -> str:
    """Append the chat-completions path unless the URL already carries it."""
    trimmed = base_url.rstrip("/")
    if trimmed.endswith("/chat/completions"):
        return trimmed
    return f"{trimmed}/chat/completions"


def default_registry_path() -> Path:
    return Path(__file__).resolve().parent / REGISTRY_FILENAME


def load_registry(path: str | os.PathLike[str] | None = None) -> dict[str, CustomModel]:
    """Load and validate the registry. Unknown top-level keys are ignored."""
    registry_path = Path(path) if path is not None else default_registry_path()
    try:
        raw = json.loads(registry_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise CustomModelError(f"custom model registry is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise CustomModelError("custom model registry must be a JSON object")
    entries = raw.get("models", {})
    if not isinstance(entries, dict):
        raise CustomModelError('custom model registry "models" must be an object')
    models: dict[str, CustomModel] = {}
    for name, entry in entries.items():
        models[name] = _validate_entry(name, entry)
    return models


def _validate_entry(name: str, entry: object) -> CustomModel:
    where = f"custom model {name!r}"
    if not isinstance(name, str) or not name.strip() or "/" in name:
        raise CustomModelError(f"{where}: name must be a non-empty slash-free string")
    if not isinstance(entry, dict):
        raise CustomModelError(f"{where}: entry must be an object")
    base_url = str(entry.get("base_url") or "").strip()
    if not base_url.startswith(("http://", "https://")):
        raise CustomModelError(f"{where}: base_url must be an http(s) URL")
    model = str(entry.get("model") or "").strip()
    if not model:
        raise CustomModelError(f"{where}: model must be a non-empty model id")
    api_key_env = entry.get("api_key_env")
    if api_key_env is not None:
        api_key_env = str(api_key_env).strip()
        if not api_key_env or not api_key_env.replace("_", "").isalnum():
            raise CustomModelError(
                f"{where}: api_key_env must be a valid env var name or null"
            )
    description = str(entry.get("description") or "")
    return CustomModel(
        name=name, base_url=base_url.rstrip("/"), model=model,
        api_key_env=api_key_env, description=description,
    )


def list_custom_models(
    path: str | os.PathLike[str] | None = None,
) -> list[CustomModel]:
    """All registered models, sorted by name."""
    return sorted(load_registry(path).values(), key=lambda entry: entry.name)


def resolve_custom_model(
    name: str,
    path: str | os.PathLike[str] | None = None,
    *,
    environ: dict[str, str] | None = None,
) -> CustomModel | None:
    """Resolve a model name against the registry. None when not registered."""
    if not name:
        return None
    return load_registry(path).get(name.strip())


def resolve_custom_model_key(
    entry: CustomModel, *, environ: dict[str, str] | None = None
) -> str | None:
    """Resolve the entry's credential, or None when the normal chain applies.

    Returns the placeholder when the entry declares a keyless endpoint, the
    named env var's value when set, else None (caller falls back to
    ``LLM_API_KEY`` and friends).
    """
    env = environ if environ is not None else os.environ
    if entry.api_key_env is None:
        return NO_KEY_PLACEHOLDER
    return (env.get(entry.api_key_env) or "").strip() or None
