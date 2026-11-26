"""Live agent adapters that borrow the TUI's OpenCode auth (no worker keys).

These are the deployment-supplied adapters for
``ARGUS_INTEGRATED_TASK_AGENTS=agent.delegation.opencode_agents:factory``. The
generator, reasoner and bootstrapper propose work only — plans, intents, facts —
through the local OpenCode server, so the request is made by OpenCode itself
with its own credentials (``auth.json`` + models.dev). The Python worker never
sees a key, and every proposal still passes through the existing validators
(``validate_generated_plan``, the strict reason/bootstrap contracts) and the
dispatcher's commit authority. Scope, egress, budget, approval and audit apply
exactly as before; only the thinking moves.

Server/model resolution, in order:

1. the run-level :class:`WorkerLlmConfig` when the driver handed one down and
   it uses ``opencode-server`` (keeps one run on one model);
2. otherwise ``OPENCODE_SERVER_URL`` (default ``http://127.0.0.1:4096``,
   ``opencode serve``'s default), ``ARGUS_OPENCODE_PROVIDER_ID`` and
   ``ARGUS_OPENCODE_MODEL_ID``.

The provider/model IDs have no default on purpose: silently picking a model
could silently bill a different tier. When they are missing the factory fails
fast with the exact variables to set. An unreachable server, a refusal, or a
non-JSON reply surfaces as an error and the task fails visibly — a live agent
never fabricates a plan, intent or fact.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from config.llm_env import worker_llm_config
from opencode_server_client import OpencodeServerClient, OpencodeServerError

logger = logging.getLogger(__name__)

SERVER_URL_ENV_VAR = "OPENCODE_SERVER_URL"
PROVIDER_ID_ENV_VAR = "ARGUS_OPENCODE_PROVIDER_ID"
MODEL_ID_ENV_VAR = "ARGUS_OPENCODE_MODEL_ID"

DEFAULT_SERVER_URL = "http://127.0.0.1:4096"

#: One retry: the free tier's most common flake is an empty reply, and a retry
#: is exactly what it needs (see opencode_server_client).
MAX_ATTEMPTS = 2
RETRY_PAUSE_SECONDS = 5.0


class OpencodeAgentsError(RuntimeError):
    """The live agents are unusable or a model reply was unusable."""


def resolve_server() -> OpencodeServerClient:
    """Build the server client from the run config or the environment."""
    run_config = worker_llm_config()
    if run_config is not None and run_config.uses_opencode_server:
        return OpencodeServerClient(
            base_url=run_config.base_url,
            model=run_config.model_id or run_config.model,
            provider_id=run_config.provider_id,
            directory=run_config.directory,
        )
    base_url = (os.getenv(SERVER_URL_ENV_VAR) or DEFAULT_SERVER_URL).strip()
    provider_id = (os.getenv(PROVIDER_ID_ENV_VAR) or "").strip()
    model_id = (os.getenv(MODEL_ID_ENV_VAR) or "").strip()
    missing = [
        name
        for name, value in (
            (PROVIDER_ID_ENV_VAR, provider_id),
            (MODEL_ID_ENV_VAR, model_id),
        )
        if not value
    ]
    if missing:
        raise OpencodeAgentsError(
            "live OpenCode agents need "
            + ", ".join(missing)
            + f" (server defaults to {DEFAULT_SERVER_URL} via {SERVER_URL_ENV_VAR}); "
            "no worker-side key is ever required"
        )
    return OpencodeServerClient(base_url=base_url, model=model_id, provider_id=provider_id)


def complete_json(client: OpencodeServerClient, *, system: str, prompt: str) -> Any:
    """Ask the server for one reply and parse it as JSON.

    Retries once when the transport explicitly marks the failure retryable.
    Anything else — a refusal, a non-JSON reply — raises, so the caller fails
    the task instead of inventing structured output.
    """
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ]
            )
            logger.info(
                "opencode completion ok (input_tokens=%d output_tokens=%d)",
                response.input_tokens,
                response.output_tokens,
            )
            return _extract_json(response.text)
        except OpencodeServerError as exc:
            last_error = exc
            if not exc.retryable or attempt == MAX_ATTEMPTS:
                raise
            logger.warning(
                "opencode completion attempt %d failed transiently: %s",
                attempt,
                exc,
            )
            time.sleep(RETRY_PAUSE_SECONDS)
    raise OpencodeAgentsError(f"opencode completion failed: {last_error}")


def _extract_json(text: str) -> Any:
    """Parse the model's reply as JSON, tolerating a single code fence."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise OpencodeAgentsError(
            "model reply was not usable JSON; refusing to fabricate structured "
            f"output (first 200 chars: {text[:200]!r})"
        ) from exc


def _facts_text(facts: list[dict[str, Any]]) -> str:
    lines = []
    for fact in facts:
        payload = fact.get("payload") if isinstance(fact, dict) else None
        summary = ""
        if isinstance(payload, dict):
            summary = str(payload.get("summary") or payload.get("text") or "")
        lines.append(f"- id={fact.get('id')}: {summary or fact}")
    return "\n".join(lines) if lines else "(none)"


class OpencodePlanGenerator:
    """Generator adapter: the model drafts the ordered subtask plan.

    Returns the raw draft list; :meth:`IntentTaskRunner._generate` validates it
    with ``validate_generated_plan`` before anything is persisted.
    """

    def __init__(self, client: OpencodeServerClient | None = None) -> None:
        self._client = client

    def _client_or_resolve(self) -> OpencodeServerClient:
        return self._client or resolve_server()

    def generate(self, request: dict[str, Any]) -> Any:
        objective = str(request.get("objective") or "")
        intent = request.get("intent") or {}
        facts = list(request.get("facts") or [])
        hints = list(request.get("hints") or [])
        max_subtasks = int(request.get("max_subtasks") or 15)
        system = (
            "You draft ordered penetration-test subtask plans as strict JSON. "
            "Reply with ONLY a JSON array, no prose, no fences."
        )
        prompt = (
            f"Objective: {objective}\n"
            f"Intent: {intent.get('objective') or objective}\n"
            f"Known facts:\n{_facts_text(facts)}\n"
            f"Hints: {hints if hints else '(none)'}\n"
            f"Draft at most {max_subtasks} subtasks as a JSON array. Each item "
            'has "title" and "description" strings and may have "depends_on", '
            "a list of earlier subtask titles it requires. Keep titles short "
            "and unique; order so dependencies come first."
        )
        return complete_json(self._client_or_resolve(), system=system, prompt=prompt)


def opencode_reasoner(
    job: dict[str, Any], client: OpencodeServerClient | None = None
) -> dict[str, Any]:
    """Reason adapter: the model proposes intents or completes the goal.

    Emits exactly what ``parse_reason_result`` accepts: ``intents`` with
    ``description``/``from`` (fact ids quoted back from the job — the parser
    rejects invented ids, so hallucinated provenance fails loudly), a
    ``complete`` block, or an empty data object meaning noop.
    """
    facts = list(job.get("facts") or [])
    open_intents = list(job.get("open_intents") or [])
    max_intents = int(job.get("max_intents") or 5)
    system = (
        "You triage penetration-test findings as strict JSON. "
        "Reply with ONLY a JSON object, no prose, no fences."
    )
    known = "\n".join(
        f"- {fact.get('id')}: {fact.get('description')}" for fact in facts
    ) or "(none)"
    already = "\n".join(
        f"- {intent.get('id')}: {intent.get('objective')}" for intent in open_intents
    ) or "(none)"
    prompt = (
        f"Facts (quote ONLY these ids in \"from\"):\n{known}\n"
        f"Already-open intents (do not duplicate):\n{already}\n"
        f"Propose at most {max_intents} NEW investigation intents as "
        '{"intents": [{"description": ..., "from": ["<fact id>", ...]}]}. '
        'If nothing new is warranted, reply {}. If the goal is proven by the '
        'facts, reply {"complete": {"description": ..., "from": [...]}}.'
    )
    data = complete_json(client or resolve_server(), system=system, prompt=prompt)
    if not isinstance(data, dict):
        raise OpencodeAgentsError(
            "reason reply must be a JSON object with intents, complete, or neither"
        )
    return {"accepted": True, "data": data}


def opencode_bootstrapper(
    job: dict[str, Any], client: OpencodeServerClient | None = None, *, conclude: bool = False
) -> dict[str, Any]:
    """Bootstrap adapter: the model states the origin fact for an engagement."""
    engagement_id = str(job.get("engagement_id") or "")
    target = job.get("target") or job.get("objective") or engagement_id
    system = (
        "You open a penetration-test engagement as strict JSON. "
        "Reply with ONLY a JSON object, no prose, no fences."
    )
    if conclude:
        prompt = (
            f"Target: {target}\n"
            'Reply {"fact": {"description": "<one sentence: what this engagement '
            'is scoped to establish>"}}.'
        )
    else:
        prompt = (
            f"Target: {target}\n"
            "Reply with BOTH keys: "
            '{"fact": {"description": "<origin fact: what is authorized to be '
            'established>"}, "complete": {"description": "<what done looks like>"}}.'
        )
    data = complete_json(client or resolve_server(), system=system, prompt=prompt)
    if not isinstance(data, dict):
        raise OpencodeAgentsError("bootstrap reply must be a JSON object")
    return {"accepted": True, "data": data}


def factory() -> dict[str, Any]:
    """Adapter mapping for ``ARGUS_INTEGRATED_TASK_AGENTS``.

    Resolves the server eagerly so a misconfigured deployment fails at startup,
    not on the first engagement.
    """
    client = resolve_server()
    return {
        "generator": OpencodePlanGenerator(client),
        "reasoner": lambda job: opencode_reasoner(job, client),
        "bootstrapper": lambda job, conclude=False: opencode_bootstrapper(
            job, client, conclude=conclude
        ),
    }
