"""Intent -> Task -> Subtasks integration (Stage 4).

The dispatcher owns durable state. For one claimed intent this module:

1. creates (or resumes) one delegation Task linked to the intent;
2. asks the Generator for a plan, validates it and persists the ordered subtasks;
3. runs the sequential :class:`TaskWorker` with the configured subtask executor,
   recording each returned action through the delegation store;
4. lets the Refiner patch the remaining plan after every terminal subtask;
5. finalizes the task and returns exactly one conclusion description, which the
   dispatcher writes as the intent's fact.

The agents stay replaceable: a Generator only proposes subtasks, the executor
only runs one bounded request and returns structured output, and the Refiner
only proposes delta operations. None of them receives the delegation store, a
claim token or graph write authority.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from agent.delegation.generator import validate_generated_plan
from agent.delegation.models import MAX_ACTIVE_SUBTASKS, DelegationError
from agent.delegation.refiner import RefinerService
from agent.delegation.reporter import Reporter
from agent.delegation.store import PostgresDelegationStore
from agent.delegation.worker import SubtaskExecutor, TaskWorker

logger = logging.getLogger(__name__)


class PlanGenerator(Protocol):
    """A Generator Agent adapter: bounded request in, subtask drafts out."""

    def generate(self, request: dict[str, Any]) -> Any: ...


class IntentTaskRunner:
    """Runs one claimed intent through the durable delegation hierarchy."""

    def __init__(
        self,
        store: PostgresDelegationStore,
        *,
        generator: PlanGenerator,
        executor: SubtaskExecutor,
        refiner: Any | None = None,
        reporter: Reporter | None = None,
        reflector: Any | None = None,
        max_steps: int = 50,
    ) -> None:
        self._store = store
        self._generator = generator
        self._executor = executor
        self._reporter = reporter or Reporter(store)
        refiner_service = (
            RefinerService(store, refiner) if refiner is not None else None
        )
        self._worker = TaskWorker(
            store,
            _RecordingExecutor(store, executor),
            refiner=refiner_service,
            reporter=self._reporter,
            reflector=reflector,
        )
        self._max_steps = max_steps

    def _task_for_intent(
        self, engagement_id: str, intent_id: str
    ) -> dict[str, Any] | None:
        for task in self._store.find_tasks_for_engagement(engagement_id):
            if str(task.get("intent_id") or "") == str(intent_id):
                return task
        return None

    def _generate(
        self,
        task: dict[str, Any],
        *,
        intent: dict[str, Any],
        facts: list[dict[str, Any]],
        hints: list[Any],
    ) -> None:
        request = {
            "task_id": str(task["id"]),
            "engagement_id": str(task["engagement_id"]),
            "objective": task["objective"],
            "intent": {
                "id": str(intent.get("id") or ""),
                "objective": str(intent.get("objective") or task["objective"]),
            },
            "facts": list(facts),
            "hints": list(hints),
            "max_subtasks": MAX_ACTIVE_SUBTASKS,
        }
        raw = self._generator.generate(request)
        plan = validate_generated_plan(raw)
        self._store.insert_plan(str(task["id"]), plan.drafts)
        logger.info(
            "intent %s planned %d subtask(s) on task %s",
            intent.get("id"),
            len(plan.drafts),
            task["id"],
        )

    def run(
        self,
        engagement_id: str,
        intent: dict[str, Any],
        *,
        facts: list[dict[str, Any]] | None = None,
        hints: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Execute one intent and return its task report plus conclusion text."""
        intent_id = str(intent.get("id") or "")
        if not intent_id:
            raise DelegationError("an intent id is required to start a task")
        objective = str(intent.get("objective") or "").strip()
        if not objective:
            raise DelegationError("an intent objective is required to start a task")

        task = self._task_for_intent(engagement_id, intent_id)
        if task is None:
            task = self._store.create_task(
                engagement_id,
                objective,
                intent_id=intent_id,
                task_context_ref=f"intent:{intent_id}",
            )
        task_id = str(task["id"])
        if task["status"] == "finished":
            return self._result(task_id)

        if not self._store.find_subtasks(task_id):
            if task["status"] != "created":
                # A task with no plan can only be planned while still created;
                # a recovered running task without subtasks is a broken write.
                raise DelegationError(
                    f"task {task_id} is {task['status']!r} with no persisted plan"
                )
            self._generate(
                task,
                intent=intent,
                facts=list(facts or []),
                hints=list(hints or []),
            )

        outcome = self._worker.run(task_id, max_steps=self._max_steps)
        if outcome.get("status") != "task_finished":
            reason = outcome.get("reason") or outcome.get("status")
            raise DelegationError(
                f"task {task_id} did not finish: {reason}"
            )
        return self._result(task_id, outcome=outcome)

    def _result(
        self, task_id: str, *, outcome: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        report = (outcome or {}).get("report")
        if report is None:
            existing = self._store.find_report(task_id)
            report = {"body": existing["body"], "created": False} if existing else None
        body = (report or {}).get("body") or {}
        description = str(body.get("summary") or "").strip()
        if not description:
            subtasks = self._store.find_subtasks(task_id)
            description = "; ".join(
                str((row.get("result") or {}).get("summary") or "").strip()
                for row in subtasks
                if (row.get("result") or {}).get("summary")
            ).strip()
        if not description:
            raise DelegationError(
                f"task {task_id} finished without a usable conclusion description"
            )
        return {
            "task_id": task_id,
            "description": description,
            "report": body,
            "subtasks": self._store.find_subtasks(task_id),
        }

    def conclusion_for_intent(
        self, engagement_id: str, intent_id: str
    ) -> str:
        """Return the persisted conclusion for an already-finished task."""
        task = self._task_for_intent(engagement_id, intent_id)
        if task is None:
            raise DelegationError(
                f"no delegation task exists for intent {intent_id}"
            )
        if task["status"] != "finished":
            raise DelegationError(
                f"task {task['id']} is {task['status']!r}; no conclusion exists yet"
            )
        return self._result(str(task["id"]))["description"]


class _RecordingExecutor:
    """Persist the structured actions returned by the real subtask executor."""

    def __init__(self, store: PostgresDelegationStore, executor: SubtaskExecutor):
        self._store = store
        self._executor = executor

    def execute(self, request: dict[str, Any]) -> Any:
        output = self._executor.execute(request)
        if not isinstance(output, dict):
            return output
        subtask = request.get("subtask") or {}
        subtask_id = str(subtask.get("id") or "")
        if not subtask_id:
            return output
        for action in output.get("actions") or []:
            if not isinstance(action, dict):
                continue
            action_id = str(action.get("action_id") or "").strip()
            if not action_id:
                continue
            try:
                self._store.record_action(
                    subtask_id,
                    action_id,
                    tool=action.get("tool"),
                    canonical_arguments=action.get("canonical_arguments") or {},
                    source_agent=action.get("source_agent")
                    or request.get("task", {}).get("id"),
                    reasoning_ref=action.get("reasoning_ref"),
                    outcome=str(action.get("outcome") or "completed"),
                    result=action.get("result") or {},
                    evidence_refs=action.get("evidence_refs") or (),
                )
            except Exception as exc:  # evidence recording must not lose the result
                logger.warning(
                    "could not record action %s for subtask %s: %s",
                    action_id,
                    subtask_id,
                    exc,
                )
        return output
