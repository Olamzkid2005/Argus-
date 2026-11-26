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
from collections.abc import Callable, Mapping
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
        heartbeat: Callable[[], None] | None = None,
        heartbeat_every: int = 1,
        operator_answers: Mapping[str, str] | None = None,
        auto_reconcile: bool = True,
    ) -> dict[str, Any]:
        """Execute one intent and return its task report plus conclusion text.

        The loop owns liveness while delegation work is in flight (plan §5.5
        puts heartbeat/reconcile on the dispatcher side, never on the agent):

        * *heartbeat* is a dispatcher-owned callback (usually the intent-claim
          heartbeat bound to this claim's token). It runs before every
          ``heartbeat_every``-th step; when it raises, the claim is lost and
          the run aborts without a conclusion.
        * a step that reports ``running_in_progress`` means a previous attempt
          died mid-subtask, so the loop reconciles the stale RUNNING row back
          to resumable and continues — no manual reconcile call needed.
        * a step that reports ``waiting_in_progress`` resumes every WAITING
          subtask that has an entry in *operator_answers* and continues; when
          no answer is available the waiting outcome is returned as-is so the
          caller can ask the operator instead of fabricating a result.
        """
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

        if auto_reconcile:
            # A previous run may have died mid-subtask; make it resumable now
            # rather than stalling on the first step.
            self._worker.reconcile(task_id)

        outcome: dict[str, Any] = {"status": "not_started"}
        for step_index in range(self._max_steps):
            if (
                heartbeat is not None
                and heartbeat_every > 0
                and step_index > 0
                and step_index % heartbeat_every == 0
            ):
                heartbeat()
            outcome = self._worker.step(task_id)
            status = outcome.get("status")
            if status == "running_in_progress":
                if auto_reconcile:
                    reconciled = self._worker.reconcile(task_id)
                    logger.info(
                        "reconciled %d stale subtask(s) on task %s",
                        len(reconciled),
                        task_id,
                    )
                    continue
                raise DelegationError(
                    f"task {task_id} stalled on a RUNNING subtask with "
                    "auto-reconcile disabled"
                )
            if status == "waiting_in_progress":
                if self._resume_waiting(task_id, operator_answers):
                    continue
                return outcome
            if status in (
                "task_finished",
                "failed",
                "dependency_blocked",
                "empty_plan",
            ):
                break
        if outcome.get("status") != "task_finished":
            reason = outcome.get("reason") or outcome.get("status")
            raise DelegationError(
                f"task {task_id} did not finish: {reason}"
            )
        return self._result(task_id, outcome=outcome)

    def _resume_waiting(
        self, task_id: str, operator_answers: Mapping[str, str] | None
    ) -> bool:
        """Resume WAITING subtasks that have an operator answer."""
        if not operator_answers:
            return False
        resumed = False
        for subtask in self._store.find_subtasks(task_id):
            if subtask.get("status") != "waiting":
                continue
            answer = operator_answers.get(str(subtask["id"]))
            if not answer:
                continue
            self._worker.resume_subtask(str(subtask["id"]), answer)
            resumed = True
            logger.info(
                "resumed waiting subtask %s on task %s with operator input",
                subtask["id"],
                task_id,
            )
        return resumed

    def _result(
        self, task_id: str, *, outcome: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        report = (outcome or {}).get("report")
        if report is None:
            existing = self._store.find_report(task_id)
            report = {"body": existing["body"], "created": False} if existing else None
        body = (report or {}).get("body") or {}
        description = str(body.get("summary") or "").strip()
        subtasks = self._store.find_subtasks(task_id)
        if not description:
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
            "subtasks": subtasks,
            "findings": self._merge_findings(subtasks),
            "anchors": self._merge_proposed(subtasks, "anchors"),
            "todos": self._merge_proposed(subtasks, "todos"),
        }

    @staticmethod
    def _merge_findings(subtasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Merge subtask-output findings with source provenance (plan §4.6)."""
        merged: list[dict[str, Any]] = []
        for row in subtasks:
            result = row.get("result") or {}
            for finding in result.get("findings") or []:
                if not isinstance(finding, dict):
                    continue
                entry = dict(finding)
                entry.setdefault("source_agent", f"subtask:{row.get('id')}")
                merged.append(entry)
        return merged

    @staticmethod
    def _merge_proposed(
        subtasks: list[dict[str, Any]], key: str
    ) -> list[dict[str, Any]]:
        """Merge generator-proposed conclusion extras (anchors/todos)."""
        merged: list[dict[str, Any]] = []
        for row in subtasks:
            arguments = row.get("arguments") or {}
            for item in arguments.get(key) or []:
                if isinstance(item, dict):
                    merged.append(dict(item))
        return merged

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
        failed: list[str] = []
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
            except Exception as exc:
                # An action whose record is lost must never read as proven
                # work: annotate the gap, and fail closed when the action
                # claimed success without persisted evidence.
                logger.warning(
                    "could not record action %s for subtask %s: %s",
                    action_id,
                    subtask_id,
                    exc,
                )
                failed.append(action_id)
                if str(action.get("outcome") or "completed").lower() in (
                    "completed",
                    "success",
                    "succeeded",
                ):
                    raise DelegationError(
                        f"action {action_id} claimed success but its record "
                        f"was lost for subtask {subtask_id} (fail closed)"
                    ) from exc
        if failed:
            gaps = list(output.get("evidence_incomplete") or [])
            gaps.extend(action_id for action_id in failed if action_id not in gaps)
            output["evidence_incomplete"] = gaps
        return output
