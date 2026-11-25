"""Typed ``task_*`` MCP protocol endpoint for the control plane.

The dispatcher talks to a worker process over the existing stdio JSON-RPC MCP
transport. Each call is one strict envelope:

``{"schema_version": 1, "task_type": "bootstrap"|"reason"|"explore",
   "conclude": bool, "request": {...}}``

This module owns the server side: it validates the envelope, rejects oversized
or unknown-field payloads and runs the configured executor. The executor gets a
bounded job and returns exactly one result payload; the dispatcher still parses
that payload with the strict contracts in :mod:`control_plane.contracts`, so a
worker can never commit graph state by replying.

The executor is deployment-specific (an agent runtime, an LLM adapter or a test
double) and is resolved from ``ARGUS_TASK_EXECUTOR=module:callable`` or set
in-process with :func:`set_task_executor`. With no executor configured every
call is explicitly rejected instead of fabricating a result.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from control_plane.contracts import ProtocolError

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

#: Methods that run a worker job and return its structured result.
EXECUTOR_METHODS: dict[str, str] = {
    "task_bootstrap": "bootstrap",
    "task_reason": "reason",
    "task_explore": "explore",
}

#: Methods that validate dispatcher-owned task control payloads. They never
#: write graph or delegation state; the dispatcher applies the result.
CONTROL_METHODS: dict[str, str] = {
    "task_generate_subtasks": "generate_subtasks",
    "task_refine_subtasks": "refine_subtasks",
    "task_progress": "progress",
    "task_cancel": "cancel",
}

#: One MCP method per typed task protocol call.
METHODS: dict[str, str] = {**EXECUTOR_METHODS, **CONTROL_METHODS}

#: Task types a worker transport advertises to the scheduler.
TASK_TYPES = frozenset(EXECUTOR_METHODS.values())

_CONTROL_KEYS: dict[str, frozenset[str]] = {
    "generate_subtasks": frozenset({"task_id", "subtasks", "existing_titles"}),
    "refine_subtasks": frozenset({"task_id", "operations"}),
    "progress": frozenset({"task_id", "subtask_id", "event"}),
    "cancel": frozenset({"task_id", "reason"}),
}

MAX_CONTROL_ITEMS = 50

#: Largest accepted request envelope (JSON bytes). A job is a bounded snapshot,
#: not a data channel; anything larger is a contract violation.
MAX_REQUEST_BYTES = 256 * 1024

_ENVELOPE_KEYS = frozenset({"schema_version", "task_type", "conclude", "request"})

#: ``(task_type, request, conclude) -> raw result payload``.
TaskExecutor = Callable[[str, dict[str, Any], bool], Any]

_executor: TaskExecutor | None = None
_executor_loaded = False


@dataclass(frozen=True)
class TaskRequest:
    method: str
    task_type: str
    conclude: bool
    request: dict[str, Any]


def _reject_unknown(data: Mapping[str, Any]) -> None:
    extras = sorted(set(data) - _ENVELOPE_KEYS)
    if extras:
        raise ProtocolError(f"task request has unknown field(s): {extras}")


def parse_task_request(method: str, params: Any) -> TaskRequest:
    """Validate one typed task envelope; any deviation is a contract violation."""
    if method not in METHODS:
        raise ProtocolError(f"unknown task method {method!r}")
    if not isinstance(params, Mapping):
        raise ProtocolError("task request must be an object")
    _reject_unknown(params)

    encoded = json.dumps(params, default=str).encode("utf-8")
    if len(encoded) > MAX_REQUEST_BYTES:
        raise ProtocolError(
            f"task request is {len(encoded)} bytes; the limit is {MAX_REQUEST_BYTES}"
        )

    version = params.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ProtocolError("schema_version must be an integer")
    if version != SCHEMA_VERSION:
        raise ProtocolError(
            f"unsupported schema_version {version}; expected {SCHEMA_VERSION}"
        )

    expected = METHODS[method]
    if params.get("task_type") != expected:
        raise ProtocolError(
            f"{method} requires task_type={expected!r}, "
            f"got {params.get('task_type')!r}"
        )

    request = params.get("request")
    if not isinstance(request, Mapping):
        raise ProtocolError("request must be an object")

    conclude = params.get("conclude", False)
    if not isinstance(conclude, bool):
        raise ProtocolError("conclude must be a boolean")

    return TaskRequest(
        method=method,
        task_type=expected,
        conclude=conclude,
        request=dict(request),
    )


def _control_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProtocolError(f"{key} must be a non-empty string")
    return value.strip()


def _run_control(request: TaskRequest) -> dict[str, Any]:
    """Validate one control payload and return its normalised data."""
    payload = request.request
    allowed = _CONTROL_KEYS[request.task_type]
    extras = sorted(set(payload) - allowed)
    if extras:
        raise ProtocolError(f"{request.task_type} has unknown field(s): {extras}")
    task_id = _control_text(payload, "task_id")

    if request.task_type == "generate_subtasks":
        subtasks = payload.get("subtasks")
        if not isinstance(subtasks, (list, tuple)) or not subtasks:
            raise ProtocolError("subtasks must be a non-empty array")
        if len(subtasks) > MAX_CONTROL_ITEMS:
            raise ProtocolError(
                f"subtasks has {len(subtasks)} items; the limit is {MAX_CONTROL_ITEMS}"
            )
        existing = payload.get("existing_titles", [])
        if not isinstance(existing, (list, tuple)) or any(
            not isinstance(item, str) for item in existing
        ):
            raise ProtocolError("existing_titles must be an array of strings")
        from agent.delegation.generator import validate_generated_plan

        try:
            plan = validate_generated_plan(
                list(subtasks), existing_titles=list(existing)
            )
        except Exception as exc:  # PlanValidationError and contract failures
            raise ProtocolError(f"invalid subtask plan: {exc}") from exc
        return {
            "task_id": task_id,
            "subtasks": [draft.as_dict() for draft in plan.drafts],
            "dropped_duplicates": list(plan.dropped_duplicates),
            "clamped": plan.clamped,
        }

    if request.task_type == "refine_subtasks":
        operations = payload.get("operations")
        if not isinstance(operations, (list, tuple)) or not operations:
            raise ProtocolError("operations must be a non-empty array")
        if len(operations) > MAX_CONTROL_ITEMS:
            raise ProtocolError(
                f"operations has {len(operations)} items; "
                f"the limit is {MAX_CONTROL_ITEMS}"
            )
        from agent.delegation.patch import PATCH_TYPES

        for index, operation in enumerate(operations):
            if not isinstance(operation, Mapping):
                raise ProtocolError(f"operations[{index}] must be an object")
            if operation.get("op") not in PATCH_TYPES:
                raise ProtocolError(
                    f"operations[{index}].op must be one of {list(PATCH_TYPES)}"
                )
        return {"task_id": task_id, "operations": [dict(op) for op in operations]}

    if request.task_type == "progress":
        subtask_id = _control_text(payload, "subtask_id")
        event = payload.get("event")
        if not isinstance(event, Mapping):
            raise ProtocolError("event must be an object")
        return {
            "task_id": task_id,
            "subtask_id": subtask_id,
            "event": dict(event),
        }

    reason = _control_text(payload, "reason")
    return {"task_id": task_id, "reason": reason}


def set_task_executor(executor: TaskExecutor | None) -> None:
    """Install (or clear) the in-process task executor."""
    global _executor, _executor_loaded
    _executor = executor
    _executor_loaded = executor is not None


def _import_executor(spec: str) -> TaskExecutor:
    module_name, separator, attribute = spec.partition(":")
    if not module_name or not separator or not attribute:
        raise RuntimeError(
            f"ARGUS_TASK_EXECUTOR must be 'module:callable'; got {spec!r}"
        )
    module = importlib.import_module(module_name)
    executor = getattr(module, attribute, None)
    if not callable(executor):
        raise RuntimeError(
            f"ARGUS_TASK_EXECUTOR target {spec!r} is not callable"
        )
    return executor


def get_task_executor() -> TaskExecutor | None:
    """Return the configured executor, resolving the env import once."""
    global _executor, _executor_loaded
    if _executor is not None:
        return _executor
    if _executor_loaded:
        return None
    _executor_loaded = True
    spec = os.getenv("ARGUS_TASK_EXECUTOR", "").strip()
    if not spec:
        return None
    _executor = _import_executor(spec)
    return _executor


def dispatch_task_request(method: str, params: Any) -> dict[str, Any]:
    """Run one typed task call and return a contract-shaped result payload.

    Validation failures and executor crashes are reported as ``accepted=false``
    so the dispatcher's parser rejects them; they never become a fact.
    """
    try:
        request = parse_task_request(method, params)
    except ProtocolError as exc:
        return {"accepted": False, "data": {}, "error": str(exc)}

    if request.task_type in CONTROL_METHODS.values():
        try:
            data = _run_control(request)
        except ProtocolError as exc:
            return {"accepted": False, "data": {}, "error": str(exc)}
        return {"accepted": True, "data": data}

    executor = get_task_executor()
    if executor is None:
        return {
            "accepted": False,
            "data": {},
            "error": (
                "no task executor is configured; set ARGUS_TASK_EXECUTOR to "
                "'module:callable' or call set_task_executor()"
            ),
        }

    try:
        result = executor(request.task_type, request.request, request.conclude)
    except Exception as exc:  # a crashed executor is a rejected result
        logger.exception("task executor failed for %s", request.task_type)
        return {
            "accepted": False,
            "data": {},
            "error": f"{type(exc).__name__}: {exc}",
        }

    if not isinstance(result, Mapping):
        return {
            "accepted": False,
            "data": {},
            "error": "task executor returned a non-object result",
        }
    return dict(result)
