"""Deterministic refiner patch validation and application (plan §4.7).

The Refiner returns delta operations, never a replacement plan. This module
applies them to an in-memory plan and either succeeds as a whole or raises
:class:`PatchValidationError`; callers persist only a successful result, so a
patch can never leave the plan half-applied.

Documented policies:

* Unknown IDs reject the entire patch (no normalisation, no partial apply).
* Started or terminal subtasks are immutable: REMOVE/MODIFY/REORDER only touch
  planned (``created``) subtasks, so completed evidence survives.
* ADD/MODIFY cannot introduce a title that duplicates planned or terminal work.
* A patch that leaves more than ``max_active`` non-terminal subtasks is rejected.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any

from agent.delegation.generator import is_duplicate, normalize_title
from agent.delegation.models import (
    MAX_ACTIVE_SUBTASKS,
    PatchValidationError,
    SubtaskStatus,
)

ADD = "ADD"
REMOVE = "REMOVE"
MODIFY = "MODIFY"
REORDER = "REORDER"
PATCH_TYPES = (ADD, REMOVE, MODIFY, REORDER)

_EDITABLE_STATUSES = frozenset({SubtaskStatus.CREATED})


@dataclass(frozen=True)
class PlanItem:
    """One subtask as the patch engine sees it."""

    id: str | None
    title: str
    description: str
    status: str = SubtaskStatus.CREATED
    depends_on: tuple[str, ...] = ()
    is_new: bool = False
    completion_condition: str | None = None

    @property
    def editable(self) -> bool:
        return self.status in _EDITABLE_STATUSES

    def same_content(self, other: PlanItem) -> bool:
        return self.title == other.title and self.description == other.description


@dataclass(frozen=True)
class PatchResult:
    items: tuple[PlanItem, ...]
    operations: tuple[dict[str, Any], ...]

    @property
    def added(self) -> tuple[PlanItem, ...]:
        return tuple(item for item in self.items if item.is_new)


def plan_items(rows: Iterable[dict[str, Any]]) -> list[PlanItem]:
    """Build patch-engine items from persisted subtask rows."""
    items = []
    for row in rows:
        depends_on = row.get("depends_on") or []
        if isinstance(depends_on, str):
            depends_on = [depends_on]
        items.append(
            PlanItem(
                id=str(row["id"]),
                title=row["title"],
                description=row["description"],
                status=row["status"],
                depends_on=tuple(str(dep) for dep in depends_on),
                completion_condition=row.get("completion_condition"),
            )
        )
    return items


def _require_text(operation: dict[str, Any], key: str, index: int) -> str:
    value = operation.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PatchValidationError(
            f"operation {index} ({operation.get('op')}) requires a non-empty {key!r}"
        )
    return value.strip()


def _find(items: list[PlanItem], subtask_id: Any, index: int) -> int:
    for position, item in enumerate(items):
        if item.id is not None and item.id == str(subtask_id):
            return position
    raise PatchValidationError(
        f"operation {index} references unknown or already-removed subtask {subtask_id!r}"
    )


def _insert_at(
    items: list[PlanItem],
    item: PlanItem,
    *,
    after_id: Any = None,
    beginning: bool = False,
) -> None:
    if after_id is None:
        if beginning:
            items.insert(0, item)
        else:
            items.append(item)
        return
    for position, existing in enumerate(items):
        if existing.id is not None and existing.id == str(after_id):
            items.insert(position + 1, item)
            return
    raise PatchValidationError(f"insertion point {after_id!r} does not exist")


def _validate_dependencies(items: list[PlanItem]) -> None:
    """Every dependency must resolve to a subtask still in the working plan."""
    ids = {str(item.id) for item in items if item.id is not None}
    titles = {normalize_title(item.title) for item in items}
    for item in items:
        for dependency in item.depends_on:
            key = str(dependency)
            if key == str(item.id):
                raise PatchValidationError(
                    f"subtask {item.title!r} cannot depend on itself"
                )
            if key in ids or normalize_title(key) in titles:
                continue
            raise PatchValidationError(
                f"subtask {item.title!r} depends on unknown or removed subtask "
                f"{dependency!r}"
            )


def _check_active(items: list[PlanItem], max_active: int) -> None:
    active = sum(1 for item in items if item.status not in (
        SubtaskStatus.FINISHED,
        SubtaskStatus.FAILED,
        SubtaskStatus.SKIPPED,
        SubtaskStatus.CANCELLED,
    ))
    if active > max_active:
        raise PatchValidationError(
            f"patch would leave {active} active subtasks; the limit is {max_active}"
        )


def _check_duplicate(
    items: list[PlanItem],
    title: str,
    *,
    ignore_index: int | None = None,
) -> None:
    others = [
        item.title
        for position, item in enumerate(items)
        if position != ignore_index
    ]
    if is_duplicate(title, others):
        raise PatchValidationError(
            f"patch would duplicate existing work: {normalize_title(title)!r}"
        )


def apply_patch(
    items: Iterable[PlanItem],
    operations: Iterable[dict[str, Any]],
    *,
    max_active: int = MAX_ACTIVE_SUBTASKS,
) -> PatchResult:
    """Apply ordered refiner operations or reject the whole patch."""
    working = [replace(item, depends_on=tuple(item.depends_on)) for item in items]
    applied = [dict(operation) for operation in operations]
    new_counter = 0

    for index, operation in enumerate(applied):
        if not isinstance(operation, dict):
            raise PatchValidationError(f"operation {index} must be an object")
        kind = str(operation.get("op") or "").upper()
        if kind not in PATCH_TYPES:
            raise PatchValidationError(
                f"operation {index} has unknown type {operation.get('op')!r}"
            )

        if kind == ADD:
            title = _require_text(operation, "title", index)
            description = _require_text(operation, "description", index)
            _check_duplicate(working, title)
            new_counter += 1
            after_id = operation.get("after_id")
            beginning = bool(operation.get("at_beginning"))
            if after_id is not None and beginning:
                raise PatchValidationError(
                    f"operation {index} cannot set both after_id and at_beginning"
                )
            _insert_at(
                working,
                PlanItem(
                    id=f"new:{new_counter}",
                    title=title,
                    description=description,
                    is_new=True,
                    depends_on=tuple(
                        str(dep) for dep in (operation.get("depends_on") or [])
                    ),
                ),
                after_id=after_id,
                beginning=beginning,
            )

        elif kind == REMOVE:
            position = _find(working, operation.get("subtask_id"), index)
            item = working[position]
            if not item.editable:
                raise PatchValidationError(
                    f"cannot remove subtask {item.id} in status {item.status!r}; "
                    "started and completed evidence is immutable"
                )
            working.pop(position)

        elif kind == MODIFY:
            position = _find(working, operation.get("subtask_id"), index)
            item = working[position]
            if not item.editable:
                raise PatchValidationError(
                    f"cannot modify subtask {item.id} in status {item.status!r}; "
                    "completed evidence is immutable"
                )
            title = operation.get("title")
            description = operation.get("description")
            if title is None and description is None:
                raise PatchValidationError(
                    f"operation {index} MODIFY changes nothing"
                )
            new_title = _require_text(operation, "title", index) if title is not None else item.title
            new_description = (
                _require_text(operation, "description", index)
                if description is not None
                else item.description
            )
            if normalize_title(new_title) != normalize_title(item.title):
                _check_duplicate(working, new_title, ignore_index=position)
            working[position] = replace(
                item, title=new_title, description=new_description
            )

        elif kind == REORDER:
            position = _find(working, operation.get("subtask_id"), index)
            item = working[position]
            if not item.editable:
                raise PatchValidationError(
                    f"cannot reorder subtask {item.id} in status {item.status!r}; "
                    "a running or completed subtask keeps its position"
                )
            working.pop(position)
            after_id = operation.get("after_id")
            beginning = bool(operation.get("at_beginning"))
            if after_id is not None and beginning:
                raise PatchValidationError(
                    f"operation {index} cannot set both after_id and at_beginning"
                )
            if after_id is not None and str(after_id) == str(item.id):
                raise PatchValidationError(
                    f"operation {index} cannot reorder a subtask after itself"
                )
            _insert_at(working, item, after_id=after_id, beginning=beginning)

        _validate_dependencies(working)
        _check_active(working, max_active)

    return PatchResult(items=tuple(working), operations=tuple(applied))
