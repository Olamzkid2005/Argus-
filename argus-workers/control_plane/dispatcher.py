"""Single-dispatcher orchestration for bootstrap, reason and explore.

The dispatcher acquires a DB-backed leadership lease per engagement, chooses a
compatible healthy worker under its running limit, claims the work, invokes the
worker with a bounded JSON job, validates the result and commits it through the
store. Workers never claim work, heartbeat a lease or write graph state.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from control_plane.contracts import (
    DEFAULT_MAX_INTENTS,
    ProtocolError,
    parse_bootstrap_conclude,
    parse_bootstrap_execute,
    parse_explore_result,
    parse_reason_result,
)
from control_plane.scheduler import WorkerView, choose_worker, global_capacity_available
from control_plane.store import LateResult, NotLeader, PostgresControlPlaneStore

logger = logging.getLogger(__name__)

#: Only a timeout or a contract violation may invoke a conclude fallback.
#: A crash, a store error or a programming bug must never look like a result.
CONCLUDE_FALLBACK_ERRORS: tuple[type[BaseException], ...] = (ProtocolError, TimeoutError)


class WorkerRunner(Protocol):
    """The dispatcher-facing worker transport (MCP bridge or test double)."""

    def supports(self, task_type: str) -> bool: ...

    def bootstrap(self, job: dict[str, Any], *, conclude: bool = False) -> Any: ...

    def reason(self, job: dict[str, Any]) -> Any: ...

    def explore(self, job: dict[str, Any], *, conclude: bool = False) -> Any: ...


class ControlPlaneDispatcher:
    def __init__(
        self,
        store: PostgresControlPlaneStore,
        runner: WorkerRunner,
        *,
        owner: str = "dispatcher",
        max_global_running: int | None = None,
        max_intents: int = DEFAULT_MAX_INTENTS,
        allow_legacy_intent: bool = False,
    ) -> None:
        self._store = store
        self._runner = runner
        self._owner = owner
        self._max_global_running = max_global_running
        self._max_intents = max_intents
        self._allow_legacy_intent = allow_legacy_intent
        self._leader_token: str | None = None

    @property
    def store(self) -> PostgresControlPlaneStore:
        return self._store

    def acquire_leadership(self, engagement_id: str, *, ttl_seconds: int = 60) -> str:
        lease = self._store.acquire_lease(
            engagement_id, "dispatcher", self._owner, ttl_seconds=ttl_seconds
        )
        if lease is None:
            raise NotLeader(
                f"another dispatcher owns scheduling authority for {engagement_id}"
            )
        self._leader_token = str(lease["token"])
        return self._leader_token

    def require_leadership(self, engagement_id: str) -> None:
        if self._leader_token is None:
            self.acquire_leadership(engagement_id)
            return
        if not self._store.holds_lease(
            engagement_id,
            "dispatcher",
            owner=self._owner,
            token=self._leader_token,
        ):
            raise NotLeader(f"leadership for {engagement_id} was lost")

    def release_leadership(self, engagement_id: str) -> None:
        if self._leader_token is None:
            return
        self._store.release_lease(
            engagement_id, "dispatcher", token=self._leader_token
        )
        self._leader_token = None

    # ----- scheduling -----

    def _workers(self) -> list[WorkerView]:
        rows = self._store.list_workers()
        return [
            WorkerView(
                worker_id=row["worker_id"],
                task_types=frozenset(row.get("task_types") or []),
                max_running=int(row["max_running"]),
                running=int(row["running"]),
                priority=int(row["priority"]),
                healthy=bool(row["healthy"]),
                unavailable_until=row.get("unavailable_until"),
                warm=int(row["running"]) > 0,
            )
            for row in rows
        ]

    def _select(self, task_type: str) -> WorkerView | None:
        workers = self._workers()
        if not global_capacity_available(
            workers, max_global_running=self._max_global_running
        ):
            return None
        return choose_worker(workers, task_type)

    def tick(self, engagement_id: str) -> str | None:
        """Run at most one protocol step for an engagement."""
        if not self._store.engagement_active(engagement_id):
            self._store.cancel_engagement_tasks(
                engagement_id, "engagement is no longer active"
            )
            if self._leader_token is not None:
                self.release_leadership(engagement_id)
            return "cancelled"

        self.require_leadership(engagement_id)

        if self._store.bootstrap_eligible(engagement_id):
            worker = self._select("bootstrap")
            if worker is not None:
                self.run_bootstrap(engagement_id, worker.worker_id)
                return "bootstrap"
            return "waiting"

        if self._store.reason_trigger(engagement_id):
            worker = self._select("reason")
            if worker is not None:
                self.run_reason(engagement_id, worker.worker_id)
                return "reason"
            return "waiting"

        if self._store.graph_counts(engagement_id)["open_intents"] > 0:
            worker = self._select("explore")
            if worker is not None:
                self.run_explore(engagement_id, worker.worker_id)
                return "explore"
            return "waiting"
        return None

    # ----- bootstrap -----

    def _bootstrap_job(self, engagement_id: str) -> dict[str, Any]:
        snapshot = self._store.reason_snapshot(engagement_id)
        goal = next(
            (row for row in snapshot["goals"] if row["state"] == "open"), None
        )
        return {
            "task_type": "bootstrap",
            "engagement_id": engagement_id,
            "origin": (goal or {}).get("origin")
            or ((goal or {}).get("payload") or {}).get("origin"),
            "goal": (goal or {}).get("payload") or {},
            "hints": [
                (row.get("payload") or {}).get("text", "")
                for row in snapshot["hints"]
            ],
            "expected": {
                "fact": "one non-empty description",
                "complete": "one non-empty description",
            },
        }

    def run_bootstrap(self, engagement_id: str, worker_id: str) -> dict[str, Any] | None:
        reservation = self._store.reserve_bootstrap(engagement_id)
        if reservation is None:
            return None
        job = self._bootstrap_job(engagement_id)
        task = self._store.start_task(engagement_id, "bootstrap", worker_id, request=job)
        try:
            payload = self._runner.bootstrap(job)
            parsed = parse_bootstrap_execute(payload)
        except CONCLUDE_FALLBACK_ERRORS as first_error:
            current = self._store.get_task(task["id"])
            if current is None or current["status"] != "running":
                return "cancelled"
            try:
                payload = self._runner.bootstrap(job, conclude=True)
                parsed_conclude = parse_bootstrap_conclude(payload)
            except CONCLUDE_FALLBACK_ERRORS as second_error:
                self._store.release_bootstrap(
                    engagement_id,
                    f"bootstrap failed: {first_error}; {second_error}",
                )
                return self._store.finish_task(
                    task["id"],
                    "failed",
                    error=f"{first_error}; conclude: {second_error}",
                )
            except Exception as exc:  # a crashed conclude is not a usable fallback
                logger.exception("bootstrap conclude crashed for %s", engagement_id)
                self._store.release_bootstrap(engagement_id, f"conclude crashed: {exc}")
                return self._store.finish_task(task["id"], "failed", error=str(exc))
            try:
                result = self._store.bootstrap_conclude_result(
                    engagement_id, parsed_conclude.fact_description, task_id=task["id"]
                )
            except LateResult as exc:
                logger.warning("bootstrap conclude rejected for %s: %s", engagement_id, exc)
                self._release_bootstrap(engagement_id, str(exc))
                return "cancelled"
            return self._store.finish_task(
                task["id"], "succeeded", result=result, conclusion_written=True
            )
        except Exception as exc:  # crash before a usable session: no fallback
            logger.exception("bootstrap executor failed for %s", engagement_id)
            self._store.release_bootstrap(engagement_id, f"bootstrap crashed: {exc}")
            return self._store.finish_task(task["id"], "failed", error=str(exc))
        try:
            result = self._store.bootstrap_execute_result(
                engagement_id,
                parsed.fact_description,
                parsed.complete_description,
                task_id=task["id"],
            )
        except LateResult as exc:
            logger.warning("bootstrap result rejected for %s: %s", engagement_id, exc)
            self._release_bootstrap(engagement_id, str(exc))
            return "cancelled"
        return self._store.finish_task(
            task["id"], "succeeded", result=result, conclusion_written=True
        )

    def _release_bootstrap(self, engagement_id: str, reason: str) -> None:
        """Release a reservation a rejected result can no longer complete."""
        try:
            self._store.release_bootstrap(engagement_id, reason)
        except ProtocolError:
            logger.debug("bootstrap reservation for %s was already gone", engagement_id)

    # ----- reason -----

    def _reason_job(self, engagement_id: str) -> dict[str, Any]:
        snapshot = self._store.reason_snapshot(engagement_id)
        return {
            "task_type": "reason",
            "engagement_id": engagement_id,
            "facts": [
                {
                    "id": str(row["id"]),
                    "description": str((row.get("payload") or {}).get("summary", "")),
                }
                for row in snapshot["facts"]
            ],
            "hints": [
                str((row.get("payload") or {}).get("text", ""))
                for row in snapshot["hints"]
            ],
            "open_intents": [
                {
                    "id": str(row["id"]),
                    "objective": str((row.get("payload") or {}).get("objective", "")),
                }
                for row in snapshot["open_intents"]
            ],
            "max_intents": self._max_intents,
            "expected": "complete, intents or noop (under the strict contract)",
        }

    def run_reason(self, engagement_id: str, worker_id: str) -> dict[str, Any] | str:
        lease = self._store.acquire_lease(
            engagement_id, "reason", self._owner, ttl_seconds=120
        )
        if lease is None:
            return "leased"
        token = str(lease["token"])
        task = self._store.start_task(
            engagement_id, "reason", worker_id, request={"trigger": "checkpoint"}
        )
        try:
            snapshot = self._store.reason_snapshot(engagement_id)
            job = self._reason_job(engagement_id)
            payload = self._runner.reason(job)
            decision = parse_reason_result(
                payload,
                valid_fact_ids=snapshot["valid_fact_ids"],
                goal_ids=snapshot["goal_ids"],
                open_intent_count=len(snapshot["open_intents"]),
                max_intents=self._max_intents,
                allow_legacy_intent=self._allow_legacy_intent,
            )
            try:
                result = self._store.apply_reason(
                    engagement_id, decision, task_id=task["id"]
                )
            except LateResult as exc:
                logger.warning("reason result rejected for %s: %s", engagement_id, exc)
                return "cancelled"
            checkpoint = self._store.record_reason_checkpoint(
                engagement_id, decision.kind
            )
            finished = self._store.finish_task(task["id"], "succeeded", result=result)
            finished["checkpoint"] = checkpoint
            return finished
        except Exception as exc:  # a failed reason run still advances the checkpoint
            logger.exception("reason task failed for %s", engagement_id)
            self._store.record_reason_checkpoint(engagement_id, "failed")
            self._store.finish_task(task["id"], "failed", error=str(exc))
            return "failed"
        finally:
            self._store.release_lease(engagement_id, "reason", token=token)

    # ----- explore -----

    def run_explore(self, engagement_id: str, worker_id: str) -> dict[str, Any] | str | None:
        claim = self._store.claim_explore(engagement_id, worker_id)
        if claim is None:
            return None
        task = claim["task"]
        job = claim["job"]
        try:
            payload = self._runner.explore(job)
            parsed = parse_explore_result(payload)
        except CONCLUDE_FALLBACK_ERRORS as first_error:
            current = self._store.get_task(task["id"])
            if current is None or current["status"] != "running":
                return "cancelled"
            if not self._store.engagement_active(engagement_id):
                self._store.cancel_task(task["id"], "engagement is no longer active")
                return "cancelled"
            try:
                payload = self._runner.explore(job, conclude=True)
                parsed = parse_explore_result(payload)
            except CONCLUDE_FALLBACK_ERRORS as second_error:
                self._store.fail_explore(
                    task["id"], f"{first_error}; conclude: {second_error}"
                )
                return "failed"
            except Exception as exc:  # a crashed conclude is not a usable fallback
                logger.exception("explore conclude crashed for %s", engagement_id)
                self._store.fail_explore(task["id"], f"conclude crashed: {exc}")
                return "failed"
            try:
                return self._store.conclude_explore(task["id"], parsed.description)
            except LateResult:
                return "cancelled"
        except Exception as exc:  # crash without a usable session: no fallback
            logger.exception("explore executor failed for %s", engagement_id)
            self._store.fail_explore(task["id"], str(exc))
            return "failed"
        try:
            return self._store.conclude_explore(task["id"], parsed.description)
        except LateResult:
            return "cancelled"

    # ----- cancellation -----

    def cancel(self, engagement_id: str, reason: str = "cancelled") -> list[dict[str, Any]]:
        """Cancel every running task; no conclude fallback may run afterwards."""
        return self._store.cancel_engagement_tasks(engagement_id, reason)
