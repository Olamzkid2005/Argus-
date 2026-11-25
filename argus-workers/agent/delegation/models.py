"""Persistent Flow/Task/Subtask/Action contracts for hierarchical delegation.

Argus maps PentAGI's hierarchy onto existing concepts (plan §4.2):

* Engagement      -> Flow
* Investigation Intent (ARTEX node) -> Task / work package
* generated plan  -> ordered Subtasks
* tool call       -> Action

Statuses are explicit and monotonic. A failed or skipped subtask is never
silently rewritten as finished: :func:`validate_subtask_transition` rejects the
transition, and :class:`SubtaskStatus` keeps the terminal states distinct.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Maximum number of active planned subtasks in one task (plan §4.5/§4.7).
MAX_ACTIVE_SUBTASKS = 15


class DelegationError(RuntimeError):
    """Base class for hierarchical delegation contract failures."""


class InvalidTransition(DelegationError):
    """A status transition that the task/subtask state machine forbids."""


class PlanValidationError(DelegationError):
    """A generated or refined plan violated the delegation contract."""


class PatchValidationError(DelegationError):
    """A refiner patch was rejected before anything was persisted."""


class TaskCompletionError(DelegationError):
    """A task cannot be completed while its subtask plan is unresolved."""


class ReflectionExhausted(DelegationError):
    """Structured output stayed invalid after the allowed repair attempts."""

    def __init__(self, message: str, *, attempts: int) -> None:
        super().__init__(message)
        self.attempts = attempts


class TaskStatus(str):
    CREATED = "created"
    RUNNING = "running"
    WAITING = "waiting"
    FINISHED = "finished"
    FAILED = "failed"


class SubtaskStatus(str):
    CREATED = "created"
    RUNNING = "running"
    WAITING = "waiting"
    FINISHED = "finished"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


TERMINAL_SUBTASK_STATUSES = frozenset(
    {
        SubtaskStatus.FINISHED,
        SubtaskStatus.FAILED,
        SubtaskStatus.SKIPPED,
        SubtaskStatus.CANCELLED,
    }
)
ACTIVE_SUBTASK_STATUSES = frozenset(
    {SubtaskStatus.CREATED, SubtaskStatus.RUNNING, SubtaskStatus.WAITING}
)
#: Terminal states that need an explicit resolution before a task may finish.
UNRESOLVED_SUBTASK_STATUSES = frozenset(
    {SubtaskStatus.FAILED, SubtaskStatus.SKIPPED, SubtaskStatus.CANCELLED}
)

_SUBTASK_TRANSITIONS: dict[str, frozenset[str]] = {
    SubtaskStatus.CREATED: frozenset(
        {SubtaskStatus.RUNNING, SubtaskStatus.SKIPPED, SubtaskStatus.CANCELLED}
    ),
    # An interrupted RUNNING subtask is reconciled back to CREATED by restart;
    # that reconciliation is deliberate and separate from a normal transition.
    SubtaskStatus.RUNNING: frozenset(
        {
            SubtaskStatus.WAITING,
            SubtaskStatus.FINISHED,
            SubtaskStatus.FAILED,
            SubtaskStatus.SKIPPED,
            SubtaskStatus.CANCELLED,
        }
    ),
    SubtaskStatus.WAITING: frozenset(
        {SubtaskStatus.RUNNING, SubtaskStatus.FAILED, SubtaskStatus.CANCELLED}
    ),
    SubtaskStatus.FINISHED: frozenset(),
    SubtaskStatus.FAILED: frozenset(),
    SubtaskStatus.SKIPPED: frozenset(),
    SubtaskStatus.CANCELLED: frozenset(),
}

_TASK_TRANSITIONS: dict[str, frozenset[str]] = {
    TaskStatus.CREATED: frozenset({TaskStatus.RUNNING, TaskStatus.FAILED}),
    TaskStatus.RUNNING: frozenset(
        {TaskStatus.WAITING, TaskStatus.FINISHED, TaskStatus.FAILED}
    ),
    TaskStatus.WAITING: frozenset(
        {TaskStatus.RUNNING, TaskStatus.FINISHED, TaskStatus.FAILED}
    ),
    TaskStatus.FINISHED: frozenset(),
    TaskStatus.FAILED: frozenset(),
}


def validate_subtask_transition(current: str, new: str) -> str:
    """Return *new* when the transition is legal, else raise ``InvalidTransition``."""
    if new not in _SUBTASK_TRANSITIONS:
        raise InvalidTransition(f"unknown subtask status: {new!r}")
    if current == new:
        raise InvalidTransition(f"subtask is already {current!r}; transitions re-enter a state")
    allowed = _SUBTASK_TRANSITIONS.get(current)
    if allowed is None:
        raise InvalidTransition(f"unknown subtask status: {current!r}")
    if new not in allowed:
        raise InvalidTransition(f"subtask cannot move from {current!r} to {new!r}")
    return new


def validate_task_transition(current: str, new: str) -> str:
    """Return *new* when the task transition is legal, else raise."""
    if new not in _TASK_TRANSITIONS:
        raise InvalidTransition(f"unknown task status: {new!r}")
    if current == new:
        raise InvalidTransition(f"task is already {current!r}; transitions re-enter a state")
    allowed = _TASK_TRANSITIONS.get(current)
    if allowed is None:
        raise InvalidTransition(f"unknown task status: {current!r}")
    if new not in allowed:
        raise InvalidTransition(f"task cannot move from {current!r} to {new!r}")
    return new


@dataclass(frozen=True)
class SubtaskDraft:
    """One generated subtask before it has a persisted identity.

    ``depends_on`` holds task-local keys: either a 0-based/1-based reference the
    generator supplied or another draft's title. :mod:`generator` normalises them
    into titles and :mod:`store` rewrites them to persisted subtask IDs.
    """

    title: str
    description: str
    depends_on: tuple[str, ...] = ()
    completion_condition: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "depends_on": list(self.depends_on),
            "completion_condition": self.completion_condition,
        }


@dataclass(frozen=True)
class Task:
    """A PentAGI Task / work package tied to one engagement and intent."""

    id: str
    engagement_id: str
    objective: str
    status: str
    intent_id: str | None = None
    generator_version: int = 1
    task_context_ref: str | None = None
    resolution: str | None = None
    created_at: Any = None
    updated_at: Any = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Task:
        return cls(
            id=str(row["id"]),
            engagement_id=str(row["engagement_id"]),
            objective=row["objective"],
            status=row["status"],
            intent_id=str(row["intent_id"]) if row.get("intent_id") else None,
            generator_version=row.get("generator_version", 1),
            task_context_ref=row.get("task_context_ref"),
            resolution=row.get("resolution"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )


@dataclass(frozen=True)
class Subtask:
    """One ordered step of a Task."""

    id: str
    task_id: str
    ordinal: int
    title: str
    description: str
    status: str
    required: bool = True
    depends_on: tuple[str, ...] = ()
    result_ref: str | None = None
    message_chain_ref: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0
    last_error: str | None = None
    resolution: str | None = None
    started_at: Any = None
    finished_at: Any = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Subtask:
        depends_on = row.get("depends_on") or []
        if isinstance(depends_on, str):
            depends_on = [depends_on]
        return cls(
            id=str(row["id"]),
            task_id=str(row["task_id"]),
            ordinal=int(row["ordinal"]),
            title=row["title"],
            description=row["description"],
            status=row["status"],
            required=bool(row.get("required", True)),
            depends_on=tuple(str(dep) for dep in depends_on),
            result_ref=row.get("result_ref"),
            message_chain_ref=row.get("message_chain_ref"),
            result=dict(row.get("result") or {}),
            retry_count=int(row.get("retry_count") or 0),
            last_error=row.get("last_error"),
            resolution=row.get("resolution"),
            started_at=row.get("started_at"),
            finished_at=row.get("finished_at"),
        )

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_SUBTASK_STATUSES


@dataclass(frozen=True)
class Action:
    """One tool operation performed while executing a Subtask."""

    id: str
    subtask_id: str
    action_id: str
    tool: str | None
    outcome: str
    canonical_arguments: dict[str, Any] = field(default_factory=dict)
    source_agent: str | None = None
    reasoning_ref: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()
    started_at: Any = None
    finished_at: Any = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Action:
        refs = row.get("evidence_refs") or []
        return cls(
            id=str(row["id"]),
            subtask_id=str(row["subtask_id"]),
            action_id=row["action_id"],
            tool=row.get("tool"),
            outcome=row.get("outcome", "completed"),
            canonical_arguments=dict(row.get("canonical_arguments") or {}),
            source_agent=row.get("source_agent"),
            reasoning_ref=row.get("reasoning_ref"),
            result=dict(row.get("result") or {}),
            evidence_refs=tuple(str(ref) for ref in refs),
            started_at=row.get("started_at"),
            finished_at=row.get("finished_at"),
        )
