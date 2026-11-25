"""PostgreSQL persistence for the fact-and-intent control plane.

The store is dispatcher-owned. It owns leader/reason leases, worker capacity,
task records with fencing tokens, reason checkpoints, the reserved bootstrap
intent and every graph write (through ``DispatcherGraph``). Workers only ever
see the job payload built here; they never receive a claim token or database
credentials.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Any

from psycopg2.extras import Json, RealDictCursor

from control_plane.contracts import ProtocolError, ReasonDecision
from database.connection import get_db
from database.dispatcher_graph import DispatcherGraph
from database.graph_errors import GraphClaimLostError
from database.graph_repository import ExplorationGraphRepository

logger = logging.getLogger(__name__)

ACTIVE_ENGAGEMENT_STATUSES = frozenset(
    {"created", "pending", "running", "scanning", "analyzing", "recon"}
)
TERMINAL_TASK_STATUSES = frozenset(
    {"succeeded", "failed", "cancelled", "rejected", "timed_out"}
)


class LeaseLost(ProtocolError):
    """The caller no longer holds the lease or claim it is writing with."""


class LateResult(ProtocolError):
    """A result arrived for a cancelled, failed or lost task."""


class NotLeader(ProtocolError):
    """Another dispatcher owns this engagement's scheduling authority."""


@contextmanager
def _cursor(commit: bool = True):
    with get_db().connection(commit=commit) as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            yield cursor
        finally:
            cursor.close()


class PostgresControlPlaneStore:
    def __init__(self, graph: DispatcherGraph | None = None) -> None:
        self._graph = graph or DispatcherGraph(ExplorationGraphRepository())

    @property
    def graph(self) -> DispatcherGraph:
        return self._graph

    # ----- engagement + graph reads -----

    def engagement_active(self, engagement_id: str) -> bool:
        status = self.engagement_status(engagement_id)
        return status is not None and status in ACTIVE_ENGAGEMENT_STATUSES

    def engagement_status(self, engagement_id: str) -> str | None:
        with _cursor(False) as cur:
            cur.execute("SELECT status FROM engagements WHERE id = %s", (engagement_id,))
            row = cur.fetchone()
        return str(row["status"]).lower() if row else None

    def graph_counts(self, engagement_id: str) -> dict[str, int]:
        with _cursor(False) as cur:
            cur.execute(
                """
                SELECT
                  COUNT(*) FILTER (
                    WHERE kind = 'fact' AND state <> 'cancelled'
                  ) AS facts,
                  COUNT(*) FILTER (WHERE kind = 'hint') AS hints,
                  COUNT(*) FILTER (
                    WHERE kind = 'intent' AND state IN ('open', 'running')
                      AND COALESCE(payload->>'bootstrap', 'false') <> 'true'
                  ) AS open_intents,
                  COUNT(*) FILTER (
                    WHERE kind = 'goal' AND state = 'open'
                  ) AS open_goals
                FROM graph_nodes WHERE engagement_id = %s
                """,
                (engagement_id,),
            )
            row = cur.fetchone()
        return {key: int(value or 0) for key, value in dict(row).items()}

    def open_goal(self, engagement_id: str) -> dict[str, Any] | None:
        with _cursor(False) as cur:
            cur.execute(
                "SELECT * FROM graph_nodes WHERE engagement_id = %s "
                "AND kind = 'goal' AND state = 'open' ORDER BY created_at ASC LIMIT 1",
                (engagement_id,),
            )
            row = cur.fetchone()
        return dict(row) if row else None

    def _find_fact(self, engagement_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        with _cursor(False) as cur:
            cur.execute(
                "SELECT * FROM graph_nodes WHERE engagement_id = %s "
                "AND kind = 'fact' AND payload @> %s ORDER BY created_at ASC LIMIT 1",
                (engagement_id, Json(payload)),
            )
            row = cur.fetchone()
        return dict(row) if row else None

    # ----- leases -----

    def acquire_lease(
        self,
        engagement_id: str,
        lease_type: str,
        owner: str,
        *,
        ttl_seconds: int = 60,
    ) -> dict[str, Any] | None:
        if lease_type not in {"dispatcher", "reason", "bootstrap"}:
            raise ProtocolError(f"unknown lease type {lease_type!r}")
        if ttl_seconds < 1:
            raise ProtocolError("ttl_seconds must be positive")
        with _cursor() as cur:
            cur.execute(
                """
                INSERT INTO control_plane_leases AS l
                    (engagement_id, lease_type, owner, expires_at)
                VALUES (%s, %s, %s, NOW() + (%s * INTERVAL '1 second'))
                ON CONFLICT (engagement_id, lease_type) DO UPDATE
                SET owner = EXCLUDED.owner,
                    token = gen_random_uuid(),
                    acquired_at = NOW(),
                    heartbeat_at = NOW(),
                    expires_at = EXCLUDED.expires_at
                WHERE l.expires_at <= NOW() OR l.owner = EXCLUDED.owner
                RETURNING *
                """,
                (engagement_id, lease_type, owner, ttl_seconds),
            )
            row = cur.fetchone()
        return dict(row) if row else None

    def heartbeat_lease(
        self,
        engagement_id: str,
        lease_type: str,
        *,
        owner: str,
        token: str,
        ttl_seconds: int = 60,
    ) -> dict[str, Any]:
        with _cursor() as cur:
            cur.execute(
                """
                UPDATE control_plane_leases
                SET heartbeat_at = NOW(),
                    expires_at = NOW() + (%s * INTERVAL '1 second')
                WHERE engagement_id = %s AND lease_type = %s
                  AND owner = %s AND token::text = %s
                RETURNING *
                """,
                (ttl_seconds, engagement_id, lease_type, owner, token),
            )
            row = cur.fetchone()
        if row is None:
            raise LeaseLost(f"{lease_type} lease for {engagement_id} is no longer held")
        return dict(row)

    def holds_lease(
        self, engagement_id: str, lease_type: str, *, owner: str, token: str
    ) -> bool:
        with _cursor(False) as cur:
            cur.execute(
                "SELECT 1 FROM control_plane_leases WHERE engagement_id = %s "
                "AND lease_type = %s AND owner = %s AND token::text = %s "
                "AND expires_at > NOW()",
                (engagement_id, lease_type, owner, token),
            )
            return cur.fetchone() is not None

    def release_lease(self, engagement_id: str, lease_type: str, *, token: str) -> bool:
        with _cursor() as cur:
            cur.execute(
                "DELETE FROM control_plane_leases WHERE engagement_id = %s "
                "AND lease_type = %s AND token::text = %s",
                (engagement_id, lease_type, token),
            )
            return cur.rowcount > 0

    def lease_holder(self, engagement_id: str, lease_type: str) -> dict[str, Any] | None:
        with _cursor(False) as cur:
            cur.execute(
                "SELECT * FROM control_plane_leases WHERE engagement_id = %s "
                "AND lease_type = %s",
                (engagement_id, lease_type),
            )
            row = cur.fetchone()
        return dict(row) if row else None

    # ----- worker registry -----

    def register_worker(
        self,
        worker_id: str,
        task_types: list[str],
        *,
        max_running: int = 1,
        priority: int = 0,
        healthy: bool = True,
    ) -> dict[str, Any]:
        if not worker_id:
            raise ProtocolError("worker_id is required")
        if max_running < 1:
            raise ProtocolError("max_running must be positive")
        with _cursor() as cur:
            cur.execute(
                """
                INSERT INTO control_plane_workers
                    (worker_id, task_types, max_running, priority, healthy)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (worker_id) DO UPDATE
                SET task_types = EXCLUDED.task_types,
                    max_running = EXCLUDED.max_running,
                    priority = EXCLUDED.priority,
                    healthy = EXCLUDED.healthy,
                    last_seen_at = NOW(),
                    updated_at = NOW()
                RETURNING *
                """,
                (worker_id, task_types, max_running, priority, healthy),
            )
            return dict(cur.fetchone())

    def set_worker_health(
        self,
        worker_id: str,
        *,
        healthy: bool,
        unavailable_for_seconds: int = 0,
    ) -> dict[str, Any]:
        with _cursor() as cur:
            cur.execute(
                """
                UPDATE control_plane_workers
                SET healthy = %s,
                    unavailable_until = CASE WHEN %s > 0
                        THEN NOW() + (%s * INTERVAL '1 second') ELSE NULL END,
                    updated_at = NOW()
                WHERE worker_id = %s
                RETURNING *
                """,
                (healthy, unavailable_for_seconds, unavailable_for_seconds, worker_id),
            )
            row = cur.fetchone()
        if row is None:
            raise ProtocolError(f"worker {worker_id!r} is not registered")
        return dict(row)

    def list_workers(self) -> list[dict[str, Any]]:
        with _cursor(False) as cur:
            cur.execute("SELECT * FROM control_plane_workers ORDER BY worker_id")
            return [dict(row) for row in cur.fetchall()]

    # ----- task records -----

    def start_task(
        self,
        engagement_id: str,
        task_type: str,
        worker_id: str,
        *,
        intent_node_id: str | None = None,
        lease_token: str | None = None,
        request: dict[str, Any] | None = None,
        timeout_seconds: int = 120,
    ) -> dict[str, Any]:
        with _cursor() as cur:
            cur.execute(
                """
                INSERT INTO control_plane_tasks
                    (engagement_id, task_type, worker_id, intent_node_id,
                     lease_token, request, deadline_at)
                VALUES (%s, %s, %s, %s, %s, %s,
                        NOW() + (%s * INTERVAL '1 second'))
                RETURNING *
                """,
                (
                    engagement_id,
                    task_type,
                    worker_id,
                    intent_node_id,
                    lease_token,
                    Json(request or {}),
                    timeout_seconds,
                ),
            )
            task = dict(cur.fetchone())
            cur.execute(
                "UPDATE control_plane_workers SET running = running + 1, "
                "last_seen_at = NOW(), updated_at = NOW() WHERE worker_id = %s",
                (worker_id,),
            )
        return task

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with _cursor(False) as cur:
            cur.execute("SELECT * FROM control_plane_tasks WHERE id = %s", (task_id,))
            row = cur.fetchone()
        return dict(row) if row else None

    def finish_task(
        self,
        task_id: str,
        status: str,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        conclusion_written: bool = False,
    ) -> dict[str, Any]:
        if status not in TERMINAL_TASK_STATUSES:
            raise ProtocolError(f"invalid terminal task status {status!r}")
        with _cursor() as cur:
            cur.execute(
                """
                UPDATE control_plane_tasks
                SET status = %s, result = %s, error = %s,
                    conclusion_written = conclusion_written OR %s,
                    finished_at = NOW(), updated_at = NOW()
                WHERE id = %s AND status = 'running'
                RETURNING *
                """,
                (status, Json(result or {}, dumps=lambda value: json.dumps(value, default=str)), error, conclusion_written, task_id),
            )
            row = cur.fetchone()
            if row is not None:
                cur.execute(
                    "UPDATE control_plane_workers SET running = GREATEST(running - 1, 0), "
                    "updated_at = NOW() WHERE worker_id = %s",
                    (row["worker_id"],),
                )
                return dict(row)
            cur.execute("SELECT * FROM control_plane_tasks WHERE id = %s", (task_id,))
            existing = cur.fetchone()
        if existing is None:
            raise ProtocolError(f"task {task_id} does not exist")
        result_row = dict(existing)
        result_row["_already_terminal"] = True
        return result_row

    def cancel_task(self, task_id: str, reason: str) -> dict[str, Any]:
        with _cursor() as cur:
            cur.execute(
                """
                UPDATE control_plane_tasks
                SET status = 'cancelled', error = %s, finished_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s AND status = 'running'
                RETURNING *
                """,
                (reason, task_id),
            )
            row = cur.fetchone()
            if row is None:
                existing = self.get_task(task_id)
                if existing is None:
                    raise ProtocolError(f"task {task_id} does not exist")
                return existing
            cur.execute(
                "UPDATE control_plane_workers SET running = GREATEST(running - 1, 0), "
                "updated_at = NOW() WHERE worker_id = %s",
                (row["worker_id"],),
            )
            task = dict(row)
        if task.get("intent_node_id"):
            self._graph.release_intent_node(
                task["engagement_id"],
                task["intent_node_id"],
                claim_token=(
                    str(task["lease_token"]) if task.get("lease_token") else None
                ),
            )
        return task

    def cancel_engagement_tasks(
        self, engagement_id: str, reason: str
    ) -> list[dict[str, Any]]:
        with _cursor(False) as cur:
            cur.execute(
                "SELECT id FROM control_plane_tasks WHERE engagement_id = %s "
                "AND status = 'running'",
                (engagement_id,),
            )
            ids = [row["id"] for row in cur.fetchall()]
        return [self.cancel_task(task_id, reason) for task_id in ids]

    # ----- reason checkpoints -----

    def reason_checkpoint(self, engagement_id: str) -> dict[str, Any] | None:
        with _cursor(False) as cur:
            cur.execute(
                "SELECT * FROM control_plane_reason_checkpoints WHERE engagement_id = %s",
                (engagement_id,),
            )
            row = cur.fetchone()
        return dict(row) if row else None

    def reason_trigger(self, engagement_id: str) -> str | None:
        counts = self.graph_counts(engagement_id)
        checkpoint = self.reason_checkpoint(engagement_id)
        if checkpoint is None:
            return "initial"
        if counts["facts"] > checkpoint["fact_count"]:
            return "facts_increased"
        if counts["hints"] > checkpoint["hint_count"]:
            return "hints_increased"
        if checkpoint["open_intent_count"] > 0 and counts["open_intents"] == 0:
            return "intents_exhausted"
        return None

    def record_reason_checkpoint(
        self, engagement_id: str, outcome: str
    ) -> dict[str, Any]:
        counts = self.graph_counts(engagement_id)
        with _cursor() as cur:
            cur.execute(
                """
                INSERT INTO control_plane_reason_checkpoints
                    (engagement_id, fact_count, hint_count, open_intent_count,
                     last_outcome)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (engagement_id) DO UPDATE
                SET fact_count = EXCLUDED.fact_count,
                    hint_count = EXCLUDED.hint_count,
                    open_intent_count = EXCLUDED.open_intent_count,
                    last_outcome = EXCLUDED.last_outcome,
                    last_run_at = NOW()
                RETURNING *
                """,
                (
                    engagement_id,
                    counts["facts"],
                    counts["hints"],
                    counts["open_intents"],
                    outcome,
                ),
            )
            return dict(cur.fetchone())

    # ----- bootstrap -----

    def bootstrap_row(self, engagement_id: str) -> dict[str, Any] | None:
        with _cursor(False) as cur:
            cur.execute(
                "SELECT * FROM control_plane_bootstrap WHERE engagement_id = %s",
                (engagement_id,),
            )
            row = cur.fetchone()
        return dict(row) if row else None

    def bootstrap_eligible(self, engagement_id: str) -> bool:
        if not self.engagement_active(engagement_id):
            return False
        row = self.bootstrap_row(engagement_id)
        if row is not None:
            return row["status"] == "reserved"
        counts = self.graph_counts(engagement_id)
        return (
            counts["open_goals"] == 1
            and counts["open_intents"] == 0
            and counts["facts"] == 0
        )

    def reserve_bootstrap(self, engagement_id: str) -> dict[str, Any] | None:
        row = self.bootstrap_row(engagement_id)
        if row is not None:
            return row if row["status"] == "reserved" else None
        goal = self.open_goal(engagement_id)
        if goal is None:
            return None
        with _cursor(False) as cur:
            cur.execute(
                "SELECT * FROM graph_nodes WHERE engagement_id = %s "
                "AND kind = 'intent' AND payload->>'bootstrap' = 'true' "
                "ORDER BY created_at ASC LIMIT 1",
                (engagement_id,),
            )
            existing = cur.fetchone()
        if existing is not None:
            reserved_intent = dict(existing)
            if reserved_intent["state"] != "reserved":
                self._graph.update_node_state(reserved_intent["id"], "reserved")
        else:
            reserved_intent = self._graph.create_node(
                engagement_id,
                "intent",
                payload={"bootstrap": True, "goal_node_id": str(goal["id"])},
                state="reserved",
                origin="dispatcher",
            )
        with _cursor() as cur:
            cur.execute(
                """
                INSERT INTO control_plane_bootstrap
                    (engagement_id, status, goal_node_id, reserved_intent_node_id)
                VALUES (%s, 'reserved', %s, %s)
                ON CONFLICT (engagement_id) DO UPDATE
                SET status = 'reserved',
                    goal_node_id = EXCLUDED.goal_node_id,
                    reserved_intent_node_id = EXCLUDED.reserved_intent_node_id,
                    attempt = control_plane_bootstrap.attempt + 1,
                    updated_at = NOW()
                RETURNING *
                """,
                (engagement_id, goal["id"], reserved_intent["id"]),
            )
            return dict(cur.fetchone())

    def mark_bootstrap(self, engagement_id: str, status: str) -> dict[str, Any]:
        if status not in {"completed", "concluded", "released"}:
            raise ProtocolError(f"invalid bootstrap status {status!r}")
        with _cursor() as cur:
            cur.execute(
                "UPDATE control_plane_bootstrap SET status = %s, updated_at = NOW() "
                "WHERE engagement_id = %s RETURNING *",
                (status, engagement_id),
            )
            row = cur.fetchone()
        if row is None:
            raise ProtocolError(f"bootstrap reservation for {engagement_id} is missing")
        return dict(row)

    def release_bootstrap(self, engagement_id: str, reason: str) -> dict[str, Any]:
        row = self.bootstrap_row(engagement_id)
        if row is None:
            raise ProtocolError(f"bootstrap reservation for {engagement_id} is missing")
        if row.get("reserved_intent_node_id"):
            self._graph.update_node_state(row["reserved_intent_node_id"], "cancelled")
        with _cursor() as cur:
            cur.execute(
                "UPDATE control_plane_bootstrap SET status = 'released', "
                "updated_at = NOW() WHERE engagement_id = %s RETURNING *",
                (engagement_id,),
            )
            released = dict(cur.fetchone())
        released["reason"] = reason
        return released

    def _write_fact(self, engagement_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        existing = self._find_fact(engagement_id, payload)
        if existing is not None:
            return existing
        return self._graph.create_node(
            engagement_id, "fact", payload=payload, state="open", origin="dispatcher"
        )

    def bootstrap_execute_result(
        self, engagement_id: str, fact_description: str, complete_description: str
    ) -> dict[str, Any]:
        row = self.bootstrap_row(engagement_id)
        if row is None or row["status"] != "reserved":
            raise ProtocolError("bootstrap is not reserved for this engagement")
        goal_id = row["goal_node_id"]
        fact = self._write_fact(
            engagement_id,
            {
                "bootstrap": True,
                "goal_node_id": str(goal_id),
                "summary": fact_description,
            },
        )
        self._graph.attach_edge(engagement_id, goal_id, fact["id"], edge_type="derives")
        self._graph.update_node_state(goal_id, "concluded")
        self.mark_bootstrap(engagement_id, "completed")
        return {"fact": fact, "goal_node_id": goal_id, "complete": complete_description}

    def bootstrap_conclude_result(
        self, engagement_id: str, fact_description: str
    ) -> dict[str, Any]:
        row = self.bootstrap_row(engagement_id)
        if row is None or row["status"] != "reserved":
            raise ProtocolError("bootstrap is not reserved for this engagement")
        fact = self._write_fact(
            engagement_id,
            {
                "bootstrap_conclusion": True,
                "goal_node_id": str(row["goal_node_id"]),
                "summary": fact_description,
            },
        )
        self.mark_bootstrap(engagement_id, "concluded")
        return {"fact": fact, "goal_node_id": row["goal_node_id"]}

    # ----- reason -----

    def reason_snapshot(self, engagement_id: str) -> dict[str, Any]:
        with _cursor(False) as cur:
            cur.execute(
                "SELECT * FROM graph_nodes WHERE engagement_id = %s "
                "AND kind IN ('goal', 'intent', 'fact', 'hint') "
                "ORDER BY created_at ASC",
                (engagement_id,),
            )
            rows = [dict(row) for row in cur.fetchall()]
        goals = [row for row in rows if row["kind"] == "goal"]
        facts = [
            row for row in rows if row["kind"] == "fact" and row["state"] != "cancelled"
        ]
        hints = [row for row in rows if row["kind"] == "hint"]
        intents = [
            row
            for row in rows
            if row["kind"] == "intent"
            and row["state"] in ("open", "running")
            and not (row.get("payload") or {}).get("bootstrap")
        ]
        return {
            "engagement_id": engagement_id,
            "goals": goals,
            "goal_ids": [str(row["id"]) for row in goals],
            "facts": facts,
            "valid_fact_ids": [str(row["id"]) for row in facts],
            "hints": hints,
            "open_intents": intents,
        }

    def apply_reason(self, engagement_id: str, decision: ReasonDecision) -> dict[str, Any]:
        if decision.kind == "noop":
            return {"kind": "noop", "created": []}
        snapshot = self.reason_snapshot(engagement_id)
        valid = set(snapshot["valid_fact_ids"])
        if decision.from_fact_ids and not set(decision.from_fact_ids) <= valid:
            raise ProtocolError("reason decision references facts outside the engagement")
        goal = next((row for row in snapshot["goals"] if row["state"] == "open"), None)
        if decision.kind == "complete":
            if goal is None:
                raise ProtocolError("reason cannot complete an engagement with no goal")
            fact = self._write_fact(
                engagement_id,
                {
                    "completion": True,
                    "goal_node_id": str(goal["id"]),
                    "from_fact_ids": sorted(decision.from_fact_ids),
                    "summary": decision.description,
                },
            )
            self._graph.attach_edge(
                engagement_id, goal["id"], fact["id"], edge_type="derives"
            )
            self._graph.update_node_state(goal["id"], "concluded")
            return {"kind": "complete", "fact": fact, "goal": goal, "created": []}
        if decision.kind != "intents":
            raise ProtocolError(f"unknown reason decision {decision.kind!r}")
        created: list[dict[str, Any]] = []
        for intent in decision.intents:
            payload = {
                "objective": intent.description,
                "from_fact_ids": sorted(intent.from_fact_ids),
                "goal_node_id": str(goal["id"]) if goal else None,
            }
            with _cursor(False) as cur:
                cur.execute(
                    "SELECT 1 FROM graph_nodes WHERE engagement_id = %s "
                    "AND kind = 'intent' AND state IN ('open', 'running') "
                    "AND payload->>'objective' = %s LIMIT 1",
                    (engagement_id, intent.description),
                )
                duplicate = cur.fetchone() is not None
            if duplicate:
                continue
            created.append(
                self._graph.create_node(
                    engagement_id,
                    "intent",
                    payload=payload,
                    state="open",
                    origin="reason",
                )
            )
        return {"kind": "intents", "created": created, "truncated": decision.truncated}

    # ----- explore -----

    def claim_explore(
        self, engagement_id: str, worker_id: str, *, lease_seconds: int = 90
    ) -> dict[str, Any] | None:
        claimed = self._graph.claim_intent_node(
            engagement_id, worker_id, lease_seconds=lease_seconds
        )
        if claimed is None:
            return None
        package = self._graph.worker_intent_package(engagement_id, claimed["id"])
        payload = {
            "intent": {
                "id": str(claimed["id"]),
                "objective": str((claimed.get("payload") or {}).get("objective", "")),
            },
            "assets": package.get("assets", []),
            "prerequisite_facts": package.get("prerequisite_facts", []),
            "hints": [
                str((row.get("payload") or {}).get("text", ""))
                for row in self.reason_snapshot(engagement_id)["hints"]
            ],
        }
        task = self.start_task(
            engagement_id,
            "explore",
            worker_id,
            intent_node_id=str(claimed["id"]),
            lease_token=str(claimed["claim_token"]),
            request=payload,
            timeout_seconds=lease_seconds,
        )
        return {"task": task, "job": self.explore_job(task)}

    def explore_job(self, task: dict[str, Any]) -> dict[str, Any]:
        request = dict(task.get("request") or {})
        return {
            "task_id": str(task["id"]),
            "task_type": "explore",
            "engagement_id": str(task["engagement_id"]),
            "intent": request.get("intent"),
            "assets": request.get("assets", []),
            "prerequisite_facts": request.get("prerequisite_facts", []),
            "hints": request.get("hints", []),
            "expected": "one non-empty fact description",
        }

    def conclude_explore(self, task_id: str, description: str) -> dict[str, Any]:
        task = self.get_task(task_id)
        if task is None:
            raise ProtocolError(f"task {task_id} does not exist")
        if task["status"] == "succeeded":
            return task
        if task["status"] != "running":
            raise LateResult(f"task {task_id} is {task['status']}; result rejected")
        if not self.engagement_active(task["engagement_id"]):
            self.cancel_task(task_id, "engagement is no longer active")
            raise LateResult("engagement stopped; result rejected")
        try:
            completed = self._graph.complete_intent_node(
                task["engagement_id"],
                task["intent_node_id"],
                claim_token=str(task["lease_token"]),
                fact_description=description,
            )
        except GraphClaimLostError as exc:
            self.finish_task(task_id, "failed", error=str(exc))
            raise LateResult(f"claim is no longer live: {exc}") from exc
        return self.finish_task(
            task_id,
            "succeeded",
            result={"fact": completed["fact"], "intent": completed["intent"]},
            conclusion_written=True,
        )

    def fail_explore(self, task_id: str, error: str) -> dict[str, Any]:
        task = self.get_task(task_id)
        if task is None:
            raise ProtocolError(f"task {task_id} does not exist")
        finished = self.finish_task(task_id, "failed", error=error)
        if task.get("intent_node_id") and not finished.get("_already_terminal"):
            self._graph.release_intent_node(
                task["engagement_id"],
                task["intent_node_id"],
                claim_token=(
                    str(task["lease_token"]) if task.get("lease_token") else None
                ),
            )
        return finished
