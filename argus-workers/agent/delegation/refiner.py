"""Refiner contract: review after each terminal subtask, then delta-patch the plan.

The Refiner Agent sees the completed result, the remaining plan and the current
facts; it returns operations, not prose. Validation and persistence happen in
:mod:`patch` and :mod:`store`, so a rejected patch leaves the plan unchanged
(P-06, P-08, P-09, P-10).
"""

from __future__ import annotations

from typing import Any, Protocol

from agent.delegation.models import MAX_ACTIVE_SUBTASKS, DelegationError
from agent.delegation.patch import PatchResult, apply_patch, plan_items


class RefinerAgent(Protocol):
    """An agent that proposes ordered delta operations for a task plan."""

    def propose(self, request: dict[str, Any]) -> Any:
        ...


def _operations(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        if "operations" in raw:
            return list(raw["operations"] or [])
        raise DelegationError("refiner response object has no 'operations' list")
    if isinstance(raw, (list, tuple)):
        return list(raw)
    raise DelegationError("refiner response must be a list of operations")


class RefinerService:
    """Builds the bounded refiner request and applies the returned patch."""

    def __init__(self, store: Any, agent: RefinerAgent | None = None) -> None:
        self._store = store
        self._agent = agent

    def build_request(
        self,
        task_id: str,
        completed_subtask_id: str,
        *,
        facts: list[dict[str, Any]] | None = None,
        graph_changes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Assemble exactly the context plan §4.7 requires the Refiner to see."""
        task = self._store.find_task(task_id)
        if task is None:
            raise DelegationError(f"task {task_id} does not exist")
        subtasks = self._store.find_subtasks(task_id)
        completed = next(
            (row for row in subtasks if str(row["id"]) == str(completed_subtask_id)),
            None,
        )
        if completed is None:
            raise DelegationError(
                f"subtask {completed_subtask_id} does not belong to task {task_id}"
            )
        if completed["status"] not in ("finished", "failed", "skipped", "cancelled"):
            raise DelegationError(
                f"refiner runs on a terminal subtask, not {completed['status']!r}"
            )
        return {
            "task_id": str(task["id"]),
            "objective": task["objective"],
            "scope": task.get("task_context_ref"),
            "completed_subtask": completed,
            "completed_result": completed.get("result") or {},
            "remaining_subtasks": [
                row
                for row in subtasks
                if row["status"] in ("created", "running", "waiting")
            ],
            "all_subtasks": subtasks,
            "facts": list(facts or []),
            "graph_changes": list(graph_changes or []),
        }

    def refine_after(
        self,
        task_id: str,
        completed_subtask_id: str,
        *,
        facts: list[dict[str, Any]] | None = None,
        graph_changes: list[dict[str, Any]] | None = None,
        rationale: str | None = None,
    ) -> dict[str, Any]:
        """Ask the Refiner for a patch and persist it atomically, or reject it."""
        if self._agent is None:
            raise DelegationError("no refiner agent is configured")
        request = self.build_request(
            task_id,
            completed_subtask_id,
            facts=facts,
            graph_changes=graph_changes,
        )
        operations = _operations(self._agent.propose(request))
        if not operations:
            return {
                "applied": False,
                "operations": [],
                "subtasks": request["all_subtasks"],
            }
        before = plan_items(request["all_subtasks"])
        result: PatchResult = apply_patch(
            before, operations, max_active=MAX_ACTIVE_SUBTASKS
        )
        persisted = self._store.apply_plan(
            task_id,
            result.items,
            trigger_subtask_id=completed_subtask_id,
            rationale=rationale or f"refined after subtask {completed_subtask_id}",
            operations=result.operations,
            expected_statuses={
                str(item.id): item.status for item in before if item.id is not None
            },
        )
        return {
            "applied": True,
            "operations": list(result.operations),
            "patch": persisted["patch"],
            "subtasks": persisted["subtasks"],
        }
