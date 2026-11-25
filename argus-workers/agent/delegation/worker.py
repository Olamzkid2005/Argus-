"""Sequential TaskWorker: one subtask at a time, Refiner after each terminal result.

Tasks are independent and may run concurrently under the ARTEX worker limits
(two tasks have separate rows and locks). Inside one task the order is strict:
only the first non-terminal subtask may start, and only after its declared
dependencies are finished (P-04, P-05).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol

from agent.delegation.models import (
    ACTIVE_SUBTASK_STATUSES,
    DelegationError,
    ReflectionExhausted,
    SubtaskStatus,
)
from agent.delegation.reflector import Reflector

logger = logging.getLogger(__name__)


class SubtaskExecutor(Protocol):
    """Runs the actual action loop for one subtask and returns structured output."""

    def execute(self, request: dict[str, Any]) -> Any:
        ...


Parser = Callable[[Any], dict[str, Any]]


def _default_parser(output: Any) -> dict[str, Any]:
    if not isinstance(output, dict):
        raise DelegationError("structured subtask output must be an object")
    summary = output.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise DelegationError("structured subtask output needs a non-empty summary")
    return output


class TaskWorker:
    """Executes one task's plan sequentially; refinement is a post-subtask hook."""

    def __init__(
        self,
        store: Any,
        executor: SubtaskExecutor,
        *,
        refiner: Any | None = None,
        reporter: Any | None = None,
        reflector: Reflector | None = None,
        parser: Parser | None = None,
    ) -> None:
        self._store = store
        self._executor = executor
        self._refiner = refiner
        self._reporter = reporter
        self._reflector = reflector or Reflector()
        self._parser = parser or _default_parser

    def step(self, task_id: str) -> dict[str, Any]:
        """Run one subtask (or finalize the task when the plan is exhausted)."""
        task = self._store.find_task(task_id)
        if task is None:
            raise DelegationError(f"task {task_id} does not exist")
        subtask, reason = self._store.claim_next_subtask(task_id)
        if subtask is None:
            if reason == "all_terminal":
                return self.finish(task_id)
            return {"status": reason, "subtask": None}

        request = {
            "task": task,
            "subtask": subtask,
            "dependencies": self._dependency_results(task_id, subtask),
            "prior_actions": self._store.find_actions(subtask["id"]),
        }
        try:
            raw = self._executor.execute(request)
            outcome = self._reflector.parse_or_repair(
                raw,
                self._parser,
                context={"subtask_id": subtask["id"], "task_id": task_id},
            ).value
        except ReflectionExhausted as exc:
            failed = self._store.transition_subtask(
                subtask["id"],
                SubtaskStatus.FAILED,
                last_error=str(exc),
                increment_retry=True,
            )
            self._after_terminal(task_id, failed)
            return {"status": "failed", "subtask": failed, "reason": str(exc)}
        except Exception as exc:
            # An executor/repair-agent failure is a terminal subtask failure, not
            # a silent RUNNING row: record it explicitly and let the Refiner see it.
            reason = f"{type(exc).__name__}: {exc}"
            failed = self._store.transition_subtask(
                subtask["id"],
                SubtaskStatus.FAILED,
                last_error=reason,
                increment_retry=True,
            )
            self._after_terminal(task_id, failed)
            return {"status": "failed", "subtask": failed, "reason": reason}

        completed = self._store.transition_subtask(
            subtask["id"],
            SubtaskStatus.FINISHED,
            result=outcome,
            result_ref=outcome.get("result_ref"),
            message_chain_ref=outcome.get("message_chain_ref")
            or subtask.get("message_chain_ref"),
        )
        self._after_terminal(task_id, completed)
        return {"status": "subtask_finished", "subtask": completed}

    def run(self, task_id: str, *, max_steps: int = 50) -> dict[str, Any]:
        """Drive the task to a terminal state or an explicit wait."""
        outcome: dict[str, Any] = {"status": "not_started"}
        for _ in range(max_steps):
            outcome = self.step(task_id)
            if outcome["status"] in (
                "task_finished",
                "failed",
                "waiting_in_progress",
                "dependency_blocked",
                "empty_plan",
            ):
                return outcome
        return outcome

    def finish(self, task_id: str) -> dict[str, Any]:
        """Finalize a fully terminal task and assemble its report once."""
        task = self._store.finalize_task(task_id)
        report = None
        if self._reporter is not None:
            report = self._reporter.report(task_id)
        return {"status": "task_finished", "task": task, "report": report}

    def pause_for_input(self, subtask_id: str, question: str) -> dict[str, Any]:
        """Persist an operator question and leave the subtask WAITING (P-13)."""
        if not question or not question.strip():
            raise DelegationError("a question is required to wait for input")
        current = self._store.find_subtask(subtask_id) or {}
        chain = current.get("message_chain_ref") or f"subtask:{subtask_id}:chain"
        return self._store.transition_subtask(
            subtask_id,
            SubtaskStatus.WAITING,
            result={"question": question.strip()},
            message_chain_ref=chain,
        )

    def resume_subtask(self, subtask_id: str, answer: str) -> dict[str, Any]:
        """Resume the same subtask/message chain after operator input (P-13)."""
        if not answer or not answer.strip():
            raise DelegationError("an answer is required to resume a waiting subtask")
        return self._store.transition_subtask(
            subtask_id,
            SubtaskStatus.RUNNING,
            result={"operator_input": answer.strip()},
        )

    def reconcile(self, task_id: str) -> dict[str, Any]:
        """Reconcile interrupted RUNNING subtasks after a restart (P-14)."""
        if self._store.find_task(task_id) is None:
            raise DelegationError(f"task {task_id} does not exist")
        reconciled = self._store.reconcile_stale_subtasks(task_id)
        return {
            "task_id": task_id,
            "reconciled": reconciled,
            "resumable": [
                str(row["id"])
                for row in reconciled
                if row["status"] == SubtaskStatus.CREATED
            ],
        }

    def _dependency_results(
        self, task_id: str, subtask: dict[str, Any]
    ) -> list[dict[str, Any]]:
        depends_on = {str(dep) for dep in subtask.get("depends_on") or []}
        if not depends_on:
            return []
        return [
            row
            for row in self._store.find_subtasks(task_id)
            if str(row["id"]) in depends_on
        ]

    def _after_terminal(self, task_id: str, subtask: dict[str, Any]) -> None:
        """Invoke the Refiner after each terminal subtask; a bad patch changes nothing."""
        if self._refiner is None:
            return
        try:
            self._refiner.refine_after(
                task_id,
                subtask["id"],
                facts=(subtask.get("result") or {}).get("facts") or [],
            )
        except Exception as exc:
            # Refinement is advisory: a rejected patch leaves the committed plan
            # intact, and a broken refiner must not undo a finished subtask.
            logger.warning(
                "Refiner patch rejected for task %s after subtask %s: %s",
                task_id,
                subtask["id"],
                exc,
            )

    def status(self, task_id: str) -> dict[str, Any]:
        task = self._store.find_task(task_id)
        if task is None:
            raise DelegationError(f"task {task_id} does not exist")
        subtasks = self._store.find_subtasks(task_id)
        return {
            "task": task,
            "subtasks": subtasks,
            "active": [
                row for row in subtasks if row["status"] in ACTIVE_SUBTASK_STATUSES
            ],
        }
