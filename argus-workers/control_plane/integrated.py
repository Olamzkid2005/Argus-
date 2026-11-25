"""Integrated worker adapter for the fact-and-intent dispatcher (Stage 4).

``IntegratedWorkerRunner`` implements the dispatcher's ``WorkerRunner`` protocol
without a separate worker process: bootstrap and reason delegate to injected
agent adapters, and explore runs the durable delegation hierarchy through
:class:`~agent.delegation.integration.IntentTaskRunner`. The dispatcher still
parses every reply with the strict contracts and performs the graph write, so
this adapter cannot commit a fact by itself.

Deployments configure the agent adapters with
``ARGUS_INTEGRATED_TASK_AGENTS=module:factory``. The factory returns a mapping
with ``generator``, ``executor``, ``reasoner`` and ``bootstrapper`` (plus
optional ``refiner`` and ``reflector``). Tests build the runner directly.
"""

from __future__ import annotations

import importlib
import logging
import os
from collections.abc import Mapping, Sequence
from typing import Any

from agent.delegation.integration import IntentTaskRunner
from agent.delegation.models import DelegationError
from agent.delegation.store import PostgresDelegationStore
from control_plane.contracts import ProtocolError

logger = logging.getLogger(__name__)

TASK_TYPES = frozenset({"bootstrap", "reason", "explore"})


class IntegratedWorkerRunner:
    """In-process WorkerRunner backed by the delegation hierarchy."""

    worker_id = "integrated-delegation"
    task_types = TASK_TYPES

    def __init__(
        self,
        *,
        intent_runner: IntentTaskRunner,
        reasoner: Any | None = None,
        bootstrapper: Any | None = None,
    ) -> None:
        self._intent_runner = intent_runner
        self._reasoner = reasoner
        self._bootstrapper = bootstrapper

    def supports(self, task_type: str) -> bool:
        return task_type in TASK_TYPES

    def bootstrap(self, job: dict[str, Any], *, conclude: bool = False) -> Any:
        if self._bootstrapper is None:
            raise ProtocolError("no bootstrap agent is configured for the integrated runner")
        return self._bootstrapper(job, conclude=conclude)

    def reason(self, job: dict[str, Any]) -> Any:
        if self._reasoner is None:
            raise ProtocolError("no reason agent is configured for the integrated runner")
        return self._reasoner(job)

    def explore(self, job: dict[str, Any], *, conclude: bool = False) -> Any:
        engagement_id = str(job.get("engagement_id") or "")
        intent = job.get("intent") or {}
        intent_id = str(intent.get("id") or "")
        if not engagement_id or not intent_id:
            raise ProtocolError("explore jobs require an engagement and intent id")
        if conclude:
            try:
                description = self._intent_runner.conclusion_for_intent(
                    engagement_id, intent_id
                )
            except DelegationError as exc:
                raise ProtocolError(str(exc)) from exc
            return {"accepted": True, "data": {"description": description}}
        try:
            result = self._intent_runner.run(
                engagement_id,
                intent,
                facts=list(job.get("prerequisite_facts") or []),
                hints=list(job.get("hints") or []),
            )
        except DelegationError as exc:
            # A delegation failure is a rejected result, not a fabricated fact.
            logger.warning("integrated explore failed for %s: %s", engagement_id, exc)
            raise ProtocolError(str(exc)) from exc
        return {
            "accepted": True,
            "data": {"description": str(result["description"])},
        }


def build_integrated_runner(
    *,
    generator: Any,
    executor: Any,
    reasoner: Any | None = None,
    bootstrapper: Any | None = None,
    refiner: Any | None = None,
    reflector: Any | None = None,
    store: PostgresDelegationStore | None = None,
    max_steps: int = 50,
) -> IntegratedWorkerRunner:
    """Build the integrated runner from agent adapters."""
    delegation_store = store or PostgresDelegationStore()
    intent_runner = IntentTaskRunner(
        delegation_store,
        generator=generator,
        executor=executor,
        refiner=refiner,
        reflector=reflector,
        max_steps=max_steps,
    )
    return IntegratedWorkerRunner(
        intent_runner=intent_runner,
        reasoner=reasoner,
        bootstrapper=bootstrapper,
    )


def _load_factory(spec: str) -> Any:
    module_name, separator, attribute = spec.partition(":")
    if not module_name or not separator or not attribute:
        raise RuntimeError(
            f"ARGUS_INTEGRATED_TASK_AGENTS must be 'module:factory'; got {spec!r}"
        )
    factory = getattr(importlib.import_module(module_name), attribute, None)
    if not callable(factory):
        raise RuntimeError(
            f"ARGUS_INTEGRATED_TASK_AGENTS target {spec!r} is not callable"
        )
    return factory


def integrated_runner_from_env() -> IntegratedWorkerRunner | None:
    """Build the integrated runner from the deployment's agent adapters."""
    spec = os.getenv("ARGUS_INTEGRATED_TASK_AGENTS", "").strip()
    if not spec:
        return None
    parts = _load_factory(spec)()
    if not isinstance(parts, Mapping):
        raise RuntimeError(
            "ARGUS_INTEGRATED_TASK_AGENTS factory must return a mapping of adapters"
        )
    allowed = {
        "generator",
        "executor",
        "reasoner",
        "bootstrapper",
        "refiner",
        "reflector",
        "store",
        "max_steps",
    }
    unknown = sorted(set(parts) - allowed)
    if unknown:
        raise RuntimeError(f"unknown integrated runner adapter(s): {unknown}")
    return build_integrated_runner(**dict(parts))


def register_task_types(runner: IntegratedWorkerRunner) -> Sequence[str]:
    """Task types the scheduler may advertise for this runner."""
    return sorted(runner.task_types)
