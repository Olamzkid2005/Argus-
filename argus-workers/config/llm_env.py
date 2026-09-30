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
