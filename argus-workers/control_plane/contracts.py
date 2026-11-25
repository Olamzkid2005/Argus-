"""Strict bootstrap/reason/explore result contracts (C-01…C-22).

Every worker result is parsed here before the dispatcher writes anything. The
parsers reject unknown keys, wrong primitive types, empty descriptions, missing
fields, invalid fact references and conflicting result forms. The singular
``intent`` alias is accepted only behind an explicit compatibility switch.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DEFAULT_MAX_INTENTS = 5


class ProtocolError(ValueError):
    """A protocol/contract violation; no durable state may change."""


class ResultRejected(ProtocolError):
    """The worker explicitly returned ``accepted=false``."""


@dataclass(frozen=True)
class BootstrapExecuteResult:
    fact_description: str
    complete_description: str


@dataclass(frozen=True)
class BootstrapConcludeResult:
    fact_description: str


@dataclass(frozen=True)
class ExploreResult:
    description: str


@dataclass(frozen=True)
class ReasonIntent:
    description: str
    from_fact_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReasonDecision:
    kind: str  # complete | intents | noop
    description: str | None = None
    from_fact_ids: tuple[str, ...] = ()
    intents: tuple[ReasonIntent, ...] = ()
    truncated: bool = False
    received_intent_count: int = 0


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProtocolError(f"{where} must be an object")
    return value


def _unknown(mapping: Mapping[str, Any], allowed: Iterable[str], where: str) -> None:
    extras = sorted(set(mapping) - set(allowed))
    if extras:
        raise ProtocolError(f"{where} has unknown field(s): {extras}")


def _text(mapping: Mapping[str, Any], key: str, where: str) -> str:
    if key not in mapping:
        raise ProtocolError(f"{where}.{key} is required")
    value = mapping[key]
    if not isinstance(value, str):
        raise ProtocolError(f"{where}.{key} must be a string")
    value = value.strip()
    if not value:
        raise ProtocolError(f"{where}.{key} must not be empty")
    return value


def _fact_ids(
    mapping: Mapping[str, Any],
    key: str,
    where: str,
    *,
    valid_fact_ids: set[str],
    goal_ids: set[str],
) -> tuple[str, ...]:
    if key not in mapping:
        raise ProtocolError(f"{where}.{key} is required")
    raw = mapping[key]
    if not isinstance(raw, (list, tuple)) or not raw:
        raise ProtocolError(f"{where}.{key} must be a non-empty array")
    ids: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ProtocolError(f"{where}.{key} entries must be non-empty strings")
        ids.append(item.strip())
    if len(set(ids)) != len(ids):
        raise ProtocolError(f"{where}.{key} must not repeat a fact id")
    goal_refs = [item for item in ids if item in goal_ids]
    if goal_refs:
        raise ProtocolError(
            f"{where}.{key} references goal ids, which are not fact sources: {goal_refs}"
        )
    unknown = [item for item in ids if item not in valid_fact_ids]
    if unknown:
        raise ProtocolError(f"{where}.{key} references unknown fact ids: {unknown}")
    return tuple(ids)


def _accepted(payload: Any, where: str) -> Mapping[str, Any]:
    result = _mapping(payload, where)
    _unknown(result, ("accepted", "data"), where)
    if "accepted" not in result or not isinstance(result["accepted"], bool):
        raise ProtocolError(f"{where}.accepted must be a boolean")
    if not result["accepted"]:
        raise ResultRejected(f"{where} was rejected (accepted=false)")
    return _mapping(result.get("data"), f"{where}.data")


def parse_bootstrap_execute(payload: Any) -> BootstrapExecuteResult:
    data = _accepted(payload, "bootstrap execute")
    _unknown(data, ("fact", "complete"), "bootstrap execute.data")
    fact = _mapping(data.get("fact"), "bootstrap execute.data.fact")
    complete = _mapping(data.get("complete"), "bootstrap execute.data.complete")
    _unknown(fact, ("description",), "bootstrap execute.data.fact")
    _unknown(complete, ("description",), "bootstrap execute.data.complete")
    return BootstrapExecuteResult(
        fact_description=_text(fact, "description", "bootstrap execute.data.fact"),
        complete_description=_text(
            complete, "description", "bootstrap execute.data.complete"
        ),
    )


def parse_bootstrap_conclude(payload: Any) -> BootstrapConcludeResult:
    data = _accepted(payload, "bootstrap conclude")
    _unknown(data, ("fact",), "bootstrap conclude.data")
    fact = _mapping(data.get("fact"), "bootstrap conclude.data.fact")
    _unknown(fact, ("description",), "bootstrap conclude.data.fact")
    return BootstrapConcludeResult(
        fact_description=_text(fact, "description", "bootstrap conclude.data.fact")
    )


def parse_explore_result(payload: Any) -> ExploreResult:
    data = _accepted(payload, "explore")
    _unknown(data, ("description",), "explore.data")
    return ExploreResult(description=_text(data, "description", "explore.data"))


def parse_reason_result(
    payload: Any,
    *,
    valid_fact_ids: Iterable[str],
    goal_ids: Iterable[str] = (),
    open_intent_count: int,
    max_intents: int = DEFAULT_MAX_INTENTS,
    allow_legacy_intent: bool = False,
) -> ReasonDecision:
    if max_intents < 1:
        raise ProtocolError("max_intents must be positive")
    facts = {str(item) for item in valid_fact_ids}
    goals = {str(item) for item in goal_ids}
    data = _accepted(payload, "reason")
    allowed = ["complete", "intents"] + (["intent"] if allow_legacy_intent else [])
    _unknown(data, allowed, "reason.data")

    has_complete = "complete" in data
    has_intents = "intents" in data or "intent" in data
    if has_complete and has_intents:
        raise ProtocolError("reason.data.complete and reason.data.intents cannot coexist")

    if has_complete:
        complete = _mapping(data["complete"], "reason.data.complete")
        _unknown(complete, ("description", "from"), "reason.data.complete")
        return ReasonDecision(
            kind="complete",
            description=_text(complete, "description", "reason.data.complete"),
            from_fact_ids=_fact_ids(
                complete,
                "from",
                "reason.data.complete",
                valid_fact_ids=facts,
                goal_ids=goals,
            ),
        )

    if has_intents:
        raw = data.get("intents")
        if "intents" not in data:
            logger.warning(
                "legacy singular 'intent' accepted; emit 'intents' instead"
            )
            raw = [data["intent"]]
        if not isinstance(raw, (list, tuple)) or not raw:
            raise ProtocolError("reason.data.intents must be a non-empty array")
        received = len(raw)
        truncated = received > max_intents
        intents: list[ReasonIntent] = []
        for index, item in enumerate(list(raw)[:max_intents]):
            where = f"reason.data.intents[{index}]"
            intent = _mapping(item, where)
            _unknown(intent, ("description", "from"), where)
            intents.append(
                ReasonIntent(
                    description=_text(intent, "description", where),
                    from_fact_ids=_fact_ids(
                        intent,
                        "from",
                        where,
                        valid_fact_ids=facts,
                        goal_ids=goals,
                    ),
                )
            )
        return ReasonDecision(
            kind="intents",
            intents=tuple(intents),
            truncated=truncated,
            received_intent_count=received,
        )

    if open_intent_count < 1:
        raise ProtocolError(
            "empty reason result is invalid with no open intents; "
            "the planner must propose at least one intent"
        )
    return ReasonDecision(kind="noop")


def parse_worker_result(kind: str, payload: Any, **kwargs: Any):
    """Dispatch one worker payload to its contract parser."""
    if kind == "bootstrap":
        return parse_bootstrap_execute(payload)
    if kind == "bootstrap_conclude":
        return parse_bootstrap_conclude(payload)
    if kind == "explore" or kind == "explore_conclude":
        return parse_explore_result(payload)
    if kind == "reason":
        return parse_reason_result(payload, **kwargs)
    raise ProtocolError(f"unknown task type {kind!r}")
