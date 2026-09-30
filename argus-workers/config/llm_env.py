"""LLM credential resolution policy for the Python workers.

Argus uses its own LLM configuration (``LLM_API_KEY`` / ``LLM_API_URL`` /
``LLM_MODEL``, normally supplied through ``argus-workers/.env``). Ambient
provider variables — ``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY``,
``OPENCODE_API_KEY``, ``GEMINI_API_KEY`` and friends — belong to whichever tool
exported them into the shell, so they are ignored unless
``ARGUS_ALLOW_AMBIENT_LLM_ENV=1`` is set explicitly.

Why this exists: the worker used to resolve its key as
``OPENAI_API_KEY or LLM_API_KEY``, so on a machine where some other tool had
exported ``OPENAI_API_KEY`` the worker silently ran — and billed — that
provider instead of the one Argus was configured with.

This mirrors
``Argus-Tui/packages/opencode/src/argus/planner/model-selection.ts``, where the
TypeScript planner resolves its provider through OpenCode's registry and
reports the ambient variables it ignored. The two policies must stay in step:
same variable list, same opt-in flag, same default.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

#: Provider variables that identify an externally-configured provider.
AMBIENT_LLM_ENV_VARS: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "ANTHROPIC_API_KEY",
    "OPENCODE_API_KEY",
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
    "AZURE_OPENAI_API_KEY",
)

#: Opt back in to ambient provider variables. Deliberately explicit.
ALLOW_AMBIENT_ENV_VAR = "ARGUS_ALLOW_AMBIENT_LLM_ENV"

#: Argus's own key variables, in precedence order.
OWN_LLM_ENV_VARS: tuple[str, ...] = ("LLM_API_KEY",)

#: Ambient variables that actually carry a credential.
_AMBIENT_KEY_VARS: tuple[str, ...] = tuple(
    name for name in AMBIENT_LLM_ENV_VARS if name.endswith("_API_KEY")
)


def _lookup(
    environ: os._Environ[str] | dict[str, str] | None,
    name: str,
) -> str | None:
    """Read one variable.

    Defaults to ``os.getenv`` rather than ``os.environ.get`` so that callers
    which patch ``os.getenv`` (the established pattern in this codebase's tests)
    observe the same values the resolver uses.
    """
    if environ is None:
        return os.getenv(name)
    return environ.get(name)


def ambient_llm_env_allowed(environ: os._Environ[str] | dict[str, str] | None = None) -> bool:
    """Whether ambient provider variables may be used."""
    return (_lookup(environ, ALLOW_AMBIENT_ENV_VAR) or "").strip().lower() in {"1", "true", "yes", "on"}


def ignored_ambient_llm_env_vars(
    environ: os._Environ[str] | dict[str, str] | None = None,
) -> list[str]:
    """Names of ambient LLM variables that are set but will not be used."""
    if ambient_llm_env_allowed(environ):
        return []
    return [name for name in AMBIENT_LLM_ENV_VARS if (_lookup(environ, name) or "").strip()]


def resolve_llm_api_key(
    explicit: str | None = None,
    environ: os._Environ[str] | dict[str, str] | None = None,
) -> str | None:
    """Resolve the LLM API key.

    Precedence: explicit argument → Argus's own variables (``LLM_API_KEY``) →
    ambient provider variables, but only when ``ARGUS_ALLOW_AMBIENT_LLM_ENV``
    opted in.

    Args:
        explicit: A key passed directly by the caller (always wins).
        environ: Environment mapping; defaults to ``os.environ``.

    Returns:
        The resolved key, or None when nothing is configured for Argus.
    """
    if explicit and explicit.strip():
        return explicit

    for name in OWN_LLM_ENV_VARS:
        value = (_lookup(environ, name) or "").strip()
        if value:
            return value

    if ambient_llm_env_allowed(environ):
        for name in _AMBIENT_KEY_VARS:
            value = (_lookup(environ, name) or "").strip()
            if value:
                return value

    return None


def ambient_ignored_note(environ: os._Environ[str] | dict[str, str] | None = None) -> str:
    """One-line explanation of ignored ambient variables, or an empty string."""
    ignored = ignored_ambient_llm_env_vars(environ)
    if not ignored:
        return ""
    return (
        f"Ignored ambient {', '.join(ignored)} — Argus uses its own LLM configuration "
        f"(set {ALLOW_AMBIENT_ENV_VAR}=1 to opt in)."
    )


# ── Run-level configuration handed down by the driver ────────────────


@dataclass(frozen=True)
class WorkerLlmConfig:
    """The model this run must use, resolved by the TypeScript planner.

    The planner is the runtime with access to OpenCode's provider registry, so
    it resolves the model once and passes the concrete endpoint to this worker
    through ``agent_init``. Without that, both runtimes would resolve
    independently and could disagree — one run planned by one model and tool
    selection performed by another.

    Two transports exist, selected by ``provider``:

    ``generic``
        An OpenAI-compatible HTTP endpoint called directly, with ``api_key``.
    ``opencode-server``
        A local OpenCode server is asked to make the call (``base_url``), so the
        request is made by OpenCode itself. OpenCode's own gateways refuse
        direct calls from a source build, so this is the only transport that can
        reach them — see docs/DEMO-READINESS-PLAN.md, blocker B9.
    """

    provider: str
    model: str
    api_key: str = ""
    api_url: str = ""
    provider_id: str = ""
    model_id: str = ""
    directory: str = ""
    base_url: str = ""
    source: str = "opencode-registry"

    @property
    def uses_opencode_server(self) -> bool:
        """Whether calls go through a local OpenCode server."""
        return self.provider == "opencode-server" and bool(self.base_url)


#: Set for the lifetime of the worker process once the driver declares it.
_run_config: WorkerLlmConfig | None = None


class InvalidWorkerLlmConfig(ValueError):
    """Raised when the driver's LLM block is unusable."""


def _chat_completions_url(base_url: str) -> str:
    """Append the chat-completions path unless the URL already carries it."""
    trimmed = base_url.rstrip("/")
    if trimmed.endswith("/chat/completions"):
        return trimmed
    return f"{trimmed}/chat/completions"


def build_worker_llm_config(payload: object) -> WorkerLlmConfig:
    """Validate an ``agent_init`` ``llm`` block.

    Two blocks are accepted, matching the two transports the worker can speak:
    ``openai-compatible`` (endpoint + key) and ``opencode-server`` (local server).

    Raises:
        InvalidWorkerLlmConfig: when required fields are missing or malformed.
    """
    if not isinstance(payload, dict):
        raise InvalidWorkerLlmConfig("llm block must be an object")

    provider = str(payload.get("provider") or "")
    model = str(payload.get("model") or "").strip()
    base_url = str(payload.get("baseUrl") or "").strip()

    if provider == "opencode-server":
        provider_id = str(payload.get("providerID") or "").strip()
        model_id = str(payload.get("modelID") or model).strip()
        directory = str(payload.get("directory") or "").strip()
        if not model_id:
            raise InvalidWorkerLlmConfig("llm.modelID is required")
        if not provider_id:
            raise InvalidWorkerLlmConfig("llm.providerID is required")
        if not base_url.startswith(("http://", "https://")):
            raise InvalidWorkerLlmConfig("llm.baseUrl must be an http(s) URL")
        return WorkerLlmConfig(
            provider="opencode-server",
            model=model_id,
            provider_id=provider_id,
            model_id=model_id,
            directory=directory,
            base_url=base_url.rstrip("/"),
        )

    if provider != "openai-compatible":
        raise InvalidWorkerLlmConfig(
            f"unsupported llm provider {provider!r}; expected 'openai-compatible' or "
            f"'opencode-server'"
        )

    api_key = str(payload.get("apiKey") or "").strip()
    if not model:
        raise InvalidWorkerLlmConfig("llm.model is required")
    if not api_key:
        raise InvalidWorkerLlmConfig("llm.apiKey is required")
    if not base_url.startswith(("http://", "https://")):
        raise InvalidWorkerLlmConfig("llm.baseUrl must be an http(s) URL")

    return WorkerLlmConfig(
        provider="generic",
        model=model,
        api_key=api_key,
        api_url=_chat_completions_url(base_url),
        provider_id=str(payload.get("providerID") or ""),
        model_id=model,
    )


def set_worker_llm_config(payload: object | None) -> WorkerLlmConfig | None:
    """Adopt the driver's LLM block for this process.

    Passing None clears it. Raises InvalidWorkerLlmConfig on a malformed block so
    the caller can report it rather than silently running on a different model
    than the planner.
    """
    global _run_config
    _run_config = None if payload is None else build_worker_llm_config(payload)
    return _run_config


def worker_llm_config() -> WorkerLlmConfig | None:
    """The run-level LLM configuration, or None when the driver did not send one."""
    return _run_config
