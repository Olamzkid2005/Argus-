"""PentAGI hierarchical delegation conformance tests (plan §4.11, P-01…P-17).

DB-backed tests run against PostgreSQL with migration 038 applied. They are
skipped when DATABASE_URL is not reachable, exactly like the graph tests,
because the delegation store uses the same repository/connection discipline.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import replace

import psycopg2
import pytest

from agent.delegation import (
    MAX_ACTIVE_SUBTASKS,
    DelegationError,
    InvalidTransition,
    Memorist,
    PatchValidationError,
    PlanItem,
    PlanValidationError,
    PostgresDelegationStore,
    PrimaryAgent,
    RefinerService,
    ReflectionExhausted,
    Reflector,
    Reporter,
    SpecialistRegistry,
    SubtaskDraft,
    SubtaskStatus,
    TaskCompletionError,
    TaskWorker,
    apply_patch,
    plan_items,
    validate_generated_plan,
)
from agent.delegation.reflector import MAX_REFLECTION_ATTEMPTS
from database.dispatcher_graph import DispatcherGraph
from database.graph_repository import ExplorationGraphRepository
from database.migrations.runner import run_migrations


def _db_available() -> bool:
    url = os.getenv("DATABASE_URL", os.getenv("TEST_DATABASE_URL"))
    if not url:
        return False
    try:
        psycopg2.connect(url, connect_timeout=3)
        return True
    except Exception:
        return False


DB_AVAILABLE = _db_available()
_SCHEMA_READY = False

pytestmark = pytest.mark.skipif(
    not DB_AVAILABLE, reason="DATABASE_URL not reachable in this environment"
)


def _ensure_schema() -> None:
    global _SCHEMA_READY
    if DB_AVAILABLE and not _SCHEMA_READY:
        run_migrations()
        _SCHEMA_READY = True


@pytest.fixture()
def store():
    _ensure_schema()
    return PostgresDelegationStore()


def _create_engagement(org_id: str | None = None) -> str:
    engagement_id = str(uuid.uuid4())
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO engagements (id, org_id, target)
                VALUES (%s, %s, %s)
                """,
                (engagement_id, org_id, "https://delegation.example.test"),
            )
    finally:
        conn.close()
    return engagement_id


def _task(store: PostgresDelegationStore, engagement_id: str, objective: str = "assess"):
    return store.create_task(engagement_id, objective)


def _plan(store: PostgresDelegationStore, task_id: str, titles: list[str]):
    drafts = [
        SubtaskDraft(title=title, description=f"do {title}")
        for title in titles
    ]
    return store.insert_plan(task_id, drafts)


def _finish_current(store: PostgresDelegationStore, task_id: str, **result):
    subtask, reason = store.claim_next_subtask(task_id)
    assert reason == "started", reason
    return store.transition_subtask(
        subtask["id"],
        SubtaskStatus.FINISHED,
        result={"summary": f"done {subtask['title']}", **result},
    )


class RecordingExecutor:
    def __init__(self, outputs: dict | None = None):
        self.requests: list[dict] = []
        self.outputs = outputs or {}

    def execute(self, request: dict):
        self.requests.append(request)
        title = request["subtask"]["title"]
        return self.outputs.get(title, {"summary": f"done {title}"})


class ScriptedRefiner:
    def __init__(self, responses: list):
        self.responses = list(responses)
        self.requests: list[dict] = []

    def propose(self, request: dict):
        self.requests.append(request)
        return self.responses.pop(0) if self.responses else []


class EchoSpecialist:
    def __init__(self, payload: dict):
        self.payload = payload
        self.requests: list[dict] = []

    def run(self, request: dict):
        self.requests.append(request)
        return self.payload


class RejectingParser:
    def __call__(self, _output):
        raise ValueError("not a structured result")


class ScriptedRepair:
    def __init__(self):
        self.calls: list[dict] = []

    def repair(self, _invalid, context):
        self.calls.append(context)
        return {"still": "unstructured"}


# ---------------------------------------------------------------------------
# P-01 — Flow/Task/Subtask/Action hierarchy and foreign-key ownership
# ---------------------------------------------------------------------------


class TestP01Hierarchy:
    def test_engagement_task_subtask_action_ownership(self, store):
        engagement_id = _create_engagement()
        other_engagement = _create_engagement()
        dispatcher = DispatcherGraph(ExplorationGraphRepository())
        intent = dispatcher.create_node(
            engagement_id,
            "intent",
            payload={"objective": "test the login flow", "source": "operator"},
        )

        # A task cannot point at another engagement's intent.
        with pytest.raises(DelegationError):
            store.create_task(
                other_engagement, "cross-engagement", intent_id=intent["id"]
            )

        task = store.create_task(
            engagement_id, "test the login flow", intent_id=intent["id"]
        )
        rows = _plan(store, task["id"], ["Enumerate", "Probe", "Confirm"])
        action = store.record_action(
            rows[0]["id"],
            "action-1",
            tool="httpx",
            canonical_arguments={"url": "https://delegation.example.test"},
            evidence_refs=["evidence-1"],
        )

        assert task["engagement_id"] == engagement_id
        assert task["intent_id"] == intent["id"]
        assert [row["task_id"] for row in rows] == [task["id"]] * 3
        assert [row["ordinal"] for row in rows] == [1, 2, 3]
        assert action["subtask_id"] == rows[0]["id"]
        assert store.find_task(task["id"])["engagement_id"] == engagement_id
        assert store.find_action(rows[0]["id"], "action-1")["evidence_refs"] == [
            "evidence-1"
        ]

    def test_status_transitions_are_monotonic(self, store):
        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        rows = _plan(store, task["id"], ["Only"])
        subtask, reason = store.claim_next_subtask(task["id"])
        assert reason == "started"

        store.transition_subtask(subtask["id"], SubtaskStatus.WAITING, result={"question": "?"})
        store.transition_subtask(subtask["id"], SubtaskStatus.RUNNING, result={"operator_input": "!"})
        store.transition_subtask(subtask["id"], SubtaskStatus.FINISHED, result={"summary": "ok"})

        with pytest.raises(DelegationError):
            store.transition_subtask(subtask["id"], SubtaskStatus.RUNNING)
        assert store.find_subtask(rows[0]["id"])["status"] == "finished"


# ---------------------------------------------------------------------------
# P-02 — a 16-subtask generator response
# ---------------------------------------------------------------------------


class TestP02GeneratorCap:
    def test_sixteen_subtasks_are_rejected_or_clamped(self, store):
        raw = [
            {"title": f"Step {index}", "description": f"step {index}"}
            for index in range(1, 17)
        ]

        with pytest.raises(PlanValidationError):
            validate_generated_plan(raw)

        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        plan = validate_generated_plan(raw, over_limit="clamp")
        assert len(plan.drafts) == MAX_ACTIVE_SUBTASKS
        assert plan.clamped is True
        rows = store.insert_plan(task["id"], plan.drafts)
        assert len(rows) == MAX_ACTIVE_SUBTASKS
        assert max(row["ordinal"] for row in rows) == MAX_ACTIVE_SUBTASKS

        # The rejected path persisted nothing.
        rejected_task = _task(store, engagement_id)
        with pytest.raises(PlanValidationError):
            validate_generated_plan(raw[:16])
        assert store.find_subtasks(rejected_task["id"]) == []


# ---------------------------------------------------------------------------
# P-03 — unordered dependencies become one deterministic valid order
# ---------------------------------------------------------------------------


class TestP03DependencyOrder:
    def test_unordered_dependencies_are_stored_in_valid_order(self, store):
        raw = [
            {"title": "third", "description": "c", "depends_on": ["second"]},
            {"title": "second", "description": "b", "depends_on": ["first"]},
            {"title": "first", "description": "a"},
        ]
        first_plan = validate_generated_plan(raw)
        second_plan = validate_generated_plan(raw)
        assert [draft.title for draft in first_plan.drafts] == [
            "first",
            "second",
            "third",
        ]
        assert [draft.title for draft in first_plan.drafts] == [
            draft.title for draft in second_plan.drafts
        ]

        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        rows = store.insert_plan(task["id"], first_plan.drafts)
        by_title = {row["title"]: row for row in rows}
        assert rows[0]["depends_on"] == []
        assert rows[1]["depends_on"] == [str(by_title["first"]["id"])]
        assert rows[2]["depends_on"] == [str(by_title["second"]["id"])]

    def test_dependency_violations_are_rejected(self):
        with pytest.raises(PlanValidationError):
            validate_generated_plan(
                [
                    {"title": "a", "description": "a", "depends_on": ["missing"]},
                ]
            )
        with pytest.raises(PlanValidationError):
            validate_generated_plan(
                [
                    {"title": "a", "description": "a", "depends_on": ["b"]},
                    {"title": "b", "description": "b", "depends_on": ["a"]},
                ]
            )


# ---------------------------------------------------------------------------
# P-04 — strict sequential execution inside one task
# ---------------------------------------------------------------------------


class TestP04SequentialExecution:
    def test_subtasks_start_in_order_only_after_predecessor_is_terminal(self, store):
        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        rows = _plan(store, task["id"], ["one", "two", "three"])

        first, reason = store.claim_next_subtask(task["id"])
        assert reason == "started"
        assert first["id"] == rows[0]["id"]
        second_attempt, reason = store.claim_next_subtask(task["id"])
        assert second_attempt is None
        assert reason == "running_in_progress"

        store.transition_subtask(first["id"], SubtaskStatus.FINISHED, result={"summary": "1"})
        second, reason = store.claim_next_subtask(task["id"])
        assert reason == "started"
        assert second["id"] == rows[1]["id"]
        assert store.claim_next_subtask(task["id"])[1] == "running_in_progress"

        store.transition_subtask(second["id"], SubtaskStatus.FINISHED, result={"summary": "2"})
        third, reason = store.claim_next_subtask(task["id"])
        assert reason == "started"
        assert third["id"] == rows[2]["id"]


# ---------------------------------------------------------------------------
# P-05 — two tasks may run concurrently; each stays sequential internally
# ---------------------------------------------------------------------------


class TestP05ConcurrentTasks:
    def test_two_tasks_run_concurrently_but_each_is_sequential(self, store):
        engagement_id = _create_engagement()
        task_a = _task(store, engagement_id, "intent A")
        task_b = _task(store, engagement_id, "intent B")
        rows_a = _plan(store, task_a["id"], ["A1", "A2"])
        rows_b = _plan(store, task_b["id"], ["B1", "B2"])

        a_first, _ = store.claim_next_subtask(task_a["id"])
        b_first, _ = store.claim_next_subtask(task_b["id"])
        assert a_first["status"] == "running"
        assert b_first["status"] == "running"
        assert store.find_task(task_a["id"])["status"] == "running"
        assert store.find_task(task_b["id"])["status"] == "running"

        # Task A still cannot run its second step while the first runs.
        assert store.claim_next_subtask(task_a["id"])[0] is None

        store.transition_subtask(a_first["id"], SubtaskStatus.FINISHED, result={"summary": "a1"})
        a_second, reason = store.claim_next_subtask(task_a["id"])
        assert reason == "started"
        assert a_second["id"] == rows_a[1]["id"]
        # B's first step is still the only running step in B.
        assert store.find_subtasks(task_b["id"])[1]["status"] == "created"
        assert b_first["id"] == rows_b[0]["id"]


# ---------------------------------------------------------------------------
# P-06 — Refiner receives completed result, remaining tasks and facts
# ---------------------------------------------------------------------------


class TestP06RefinerInvocation:
    def test_refiner_gets_completed_result_remaining_plan_and_facts(self, store):
        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        rows = _plan(store, task["id"], ["First", "Second", "Third"])
        completed = _finish_current(
            store, task["id"], findings=[{"asset": "api", "type": "header"}]
        )
        agent = ScriptedRefiner([[]])
        service = RefinerService(store, agent)

        outcome = service.refine_after(
            task["id"],
            completed["id"],
            facts=[{"fact": "server is nginx"}],
            graph_changes=[{"change": "endpoint discovered"}],
        )

        assert outcome["applied"] is False
        request = agent.requests[0]
        assert request["objective"] == "assess"
        assert request["completed_subtask"]["id"] == completed["id"]
        assert request["completed_result"]["summary"] == "done First"
        assert [row["title"] for row in request["remaining_subtasks"]] == [
            "Second",
            "Third",
        ]
        assert request["facts"] == [{"fact": "server is nginx"}]
        assert request["graph_changes"] == [{"change": "endpoint discovered"}]
        assert [row["id"] for row in request["all_subtasks"]] == [
            str(row["id"]) for row in rows
        ]


# ---------------------------------------------------------------------------
# P-07 — every patch type and insertion ordering
# ---------------------------------------------------------------------------


class TestP07PatchTypes:
    def test_add_remove_modify_reorder_match_delta_semantics(self, store):
        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        rows = _plan(store, task["id"], ["one", "two", "three", "four"])
        by_title = {row["title"]: str(row["id"]) for row in rows}

        operations = [
            {"op": "ADD", "title": "zero", "description": "before", "at_beginning": True},
            {
                "op": "ADD",
                "title": "between",
                "description": "after two",
                "after_id": by_title["two"],
            },
            {
                "op": "MODIFY",
                "subtask_id": by_title["three"],
                "title": "three updated",
            },
            {
                "op": "REORDER",
                "subtask_id": by_title["four"],
                "after_id": by_title["one"],
            },
            {"op": "REMOVE", "subtask_id": by_title["two"]},
        ]
        result = apply_patch(plan_items(rows), operations)
        persisted = store.apply_plan(
            task["id"],
            result.items,
            trigger_subtask_id=None,
            rationale="exercise every patch type",
            operations=result.operations,
        )

        assert [(row["ordinal"], row["title"]) for row in persisted["subtasks"]] == [
            (1, "zero"),
            (2, "one"),
            (3, "four"),
            (4, "between"),
            (5, "three updated"),
        ]
        patches = store.find_patches(task["id"])
        assert len(patches) == 1
        assert [op["op"] for op in patches[0]["operations"]] == [
            "ADD",
            "ADD",
            "MODIFY",
            "REORDER",
            "REMOVE",
        ]


# ---------------------------------------------------------------------------
# P-08 — unknown reference rejects the whole patch
# ---------------------------------------------------------------------------


class TestP08UnknownReference:
    def test_unknown_id_rejects_patch_without_partial_corruption(self, store):
        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        _plan(store, task["id"], ["first", "second"])
        completed = _finish_current(store, task["id"])
        before = store.find_subtasks(task["id"])
        agent = ScriptedRefiner(
            [
                [
                    {"op": "ADD", "title": "valid", "description": "would apply"},
                    {
                        "op": "REMOVE",
                        "subtask_id": "00000000-0000-0000-0000-000000000000",
                    },
                ]
            ]
        )
        service = RefinerService(store, agent)

        with pytest.raises(PatchValidationError):
            service.refine_after(task["id"], completed["id"])

        after = store.find_subtasks(task["id"])
        assert [(row["id"], row["ordinal"], row["title"]) for row in after] == [
            (row["id"], row["ordinal"], row["title"]) for row in before
        ]
        assert store.find_patches(task["id"]) == []


# ---------------------------------------------------------------------------
# P-09 — completed evidence is immutable
# ---------------------------------------------------------------------------


class TestP09CompletedEvidence:
    def test_refiner_cannot_edit_a_completed_subtask(self, store):
        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        _plan(store, task["id"], ["complete me", "remaining"])
        completed = _finish_current(
            store, task["id"], findings=[{"asset": "api", "type": "xss"}]
        )
        before = store.find_subtask(completed["id"])
        agent = ScriptedRefiner(
            [
                [
                    {
                        "op": "MODIFY",
                        "subtask_id": completed["id"],
                        "title": "rewrite the evidence",
                        "description": "rewrite the evidence",
                    }
                ]
            ]
        )

        with pytest.raises(PatchValidationError):
            RefinerService(store, agent).refine_after(task["id"], completed["id"])

        after = store.find_subtask(completed["id"])
        assert after["status"] == "finished"
        assert after["title"] == before["title"] == "complete me"
        assert after["result"] == before["result"]
        assert store.find_patches(task["id"]) == []


# ---------------------------------------------------------------------------
# P-10 — a patch that would create 16 active subtasks is rejected
# ---------------------------------------------------------------------------


class TestP10ActiveCap:
    def test_patch_over_the_active_cap_is_rejected(self, store):
        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        rows = _plan(
            store,
            task["id"],
            [f"step {index}" for index in range(1, MAX_ACTIVE_SUBTASKS + 1)],
        )
        before = store.find_subtasks(task["id"])

        with pytest.raises(PatchValidationError):
            apply_patch(
                plan_items(rows),
                [{"op": "ADD", "title": "one too many", "description": "overflow"}],
            )

        # Nothing was persisted by the rejected patch.
        after = store.find_subtasks(task["id"])
        assert len(after) == MAX_ACTIVE_SUBTASKS
        assert [row["title"] for row in after] == [row["title"] for row in before]
        assert store.find_patches(task["id"]) == []


# ---------------------------------------------------------------------------
# P-11 — bounded specialist delegation, provenance, no direct DB mutation
# ---------------------------------------------------------------------------


class TestP11SpecialistDelegation:
    def test_specialist_gets_bounded_context_and_returns_provenance(self, store):
        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        rows = _plan(store, task["id"], ["probe"])
        subtask_count = len(store.find_subtasks(task["id"]))
        action_count = len(store.find_actions(rows[0]["id"]))

        registry = SpecialistRegistry()
        pentester = EchoSpecialist(
            {
                "status": "ok",
                "summary": "found an exposed admin panel",
                "findings": [
                    {"asset": "admin", "type": "auth_bypass", "severity": "high"}
                ],
                "evidence_refs": ["evidence-11"],
            }
        )
        registry.register("pentester", {"http", "exploit"}, pentester)
        primary = PrimaryAgent(registry, max_facts=3, max_targets=2, max_tools=2)

        outcome = primary.handle(
            rows[0],
            capabilities={"http"},
            facts=[{"id": index} for index in range(10)],
            authorized_targets=[f"target-{index}" for index in range(10)],
            allowed_tools=["httpx", "nuclei", "sqlmap"],
            engagement_id=engagement_id,
        )

        payload = pentester.requests[0]
        assert payload["role"] == "pentester"
        assert len(payload["facts"]) == 3
        assert payload["authorized_targets"] == ["target-0", "target-1"]
        assert payload["allowed_tools"] == ["httpx", "nuclei"]
        assert outcome.merged_findings[0]["source_agent"] == "pentester"
        assert outcome.provenance[0]["role"] == "pentester"
        assert outcome.as_result()["evidence_refs"] == ["evidence-11"]

        # The Primary Agent and specialists hold no store: nothing was written.
        assert len(store.find_subtasks(task["id"])) == subtask_count
        assert len(store.find_actions(rows[0]["id"])) == action_count

    def test_conflicting_specialist_findings_go_to_verification(self):
        registry = SpecialistRegistry()
        registry.register(
            "pentester",
            {"http"},
            EchoSpecialist(
                {
                    "summary": "exploitable",
                    "findings": [
                        {"asset": "api", "type": "sqli", "severity": "high"}
                    ],
                }
            ),
        )
        registry.register(
            "adviser",
            {"http"},
            EchoSpecialist(
                {
                    "summary": "not exploitable",
                    "findings": [
                        {"asset": "api", "type": "sqli", "severity": "low"}
                    ],
                }
            ),
        )
        outcome = PrimaryAgent(registry).handle(
            {"id": "s", "title": "probe", "description": "probe"},
            capabilities={"http"},
        )
        assert outcome.conflicts
        assert outcome.conflicts[0]["resolution"] == "requires_verification"
        assert outcome.conflicts[0]["values"] == ["high", "low"]


# ---------------------------------------------------------------------------
# P-12 — Reflector gets at most three attempts and failure is explicit
# ---------------------------------------------------------------------------


class TestP12ReflectionLimit:
    def test_reflector_stops_after_three_attempts(self):
        repair = ScriptedRepair()
        reflector = Reflector(repair, max_attempts=MAX_REFLECTION_ATTEMPTS)

        with pytest.raises(ReflectionExhausted) as excinfo:
            reflector.parse_or_repair("junk", RejectingParser())

        assert excinfo.value.attempts == MAX_REFLECTION_ATTEMPTS == 3
        assert len(repair.calls) == 3
        assert [call["attempt"] for call in repair.calls] == [1, 2, 3]

    def test_invalid_output_marks_the_subtask_failed_not_finished(self, store):
        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        _plan(store, task["id"], ["needs structure"])
        executor = RecordingExecutor({"needs structure": {"unstructured": True}})
        repair = ScriptedRepair()
        worker = TaskWorker(
            store,
            executor,
            reflector=Reflector(repair, max_attempts=MAX_REFLECTION_ATTEMPTS),
            parser=RejectingParser(),
        )

        outcome = worker.step(task["id"])

        assert outcome["status"] == "failed"
        subtask = store.find_subtasks(task["id"])[0]
        assert subtask["status"] == "failed"
        assert "3 repair" in subtask["last_error"]
        assert store.find_task(task["id"])["status"] == "running"
        with pytest.raises(TaskCompletionError):
            store.finalize_task(task["id"])


# ---------------------------------------------------------------------------
# P-13 — operator input pauses and resumes the same context
# ---------------------------------------------------------------------------


class TestP13Waiting:
    def test_waiting_subtask_resumes_same_task_and_chain(self, store):
        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        _plan(store, task["id"], ["needs credentials"])
        worker = TaskWorker(store, RecordingExecutor())
        subtask, reason = store.claim_next_subtask(task["id"])
        assert reason == "started"

        waiting = worker.pause_for_input(subtask["id"], "Which role should be used?")
        assert waiting["status"] == "waiting"
        assert waiting["result"]["question"] == "Which role should be used?"
        chain = waiting["message_chain_ref"]
        assert chain

        # Nothing else starts while the task waits.
        assert store.claim_next_subtask(task["id"])[1] == "waiting_in_progress"

        resumed = worker.resume_subtask(subtask["id"], "use the read-only role")
        assert resumed["status"] == "running"
        assert resumed["task_id"] == task["id"]
        assert resumed["message_chain_ref"] == chain
        assert resumed["result"]["operator_input"] == "use the read-only role"


# ---------------------------------------------------------------------------
# P-14 — restart reconciles RUNNING subtasks without blind replay
# ---------------------------------------------------------------------------


class TestP14RestartRecovery:
    def test_interrupted_subtask_becomes_resumable_and_reuses_actions(self, store):
        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        _plan(store, task["id"], ["interrupted"])
        worker = TaskWorker(store, RecordingExecutor())
        subtask, _ = store.claim_next_subtask(task["id"])
        store.transition_subtask(
            subtask["id"],
            SubtaskStatus.WAITING,
            result={"question": "continue?"},
            message_chain_ref="chain-14",
        )
        store.transition_subtask(
            subtask["id"], SubtaskStatus.RUNNING, result={"operator_input": "yes"}
        )
        original = store.record_action(
            subtask["id"],
            "action-before-crash",
            tool="httpx",
            result={"status": 200},
            evidence_refs=["evidence-before-crash"],
        )

        reconciliation = worker.reconcile(task["id"])

        assert reconciliation["resumable"] == [str(subtask["id"])]
        reconciled = store.find_subtask(subtask["id"])
        assert reconciled["status"] == "created"
        assert reconciled["message_chain_ref"] == "chain-14"
        assert "interrupted" in reconciled["last_error"]
        assert (
            store.find_action(subtask["id"], "action-before-crash")["id"]
            == original["id"]
        )

        executor = RecordingExecutor({"interrupted": {"summary": "resumed safely"}})
        resuming_worker = TaskWorker(store, executor)
        outcome = resuming_worker.step(task["id"])

        assert outcome["status"] == "subtask_finished"
        request = executor.requests[0]
        assert [action["action_id"] for action in request["prior_actions"]] == [
            "action-before-crash"
        ]
        assert len(store.find_actions(subtask["id"])) == 1


# ---------------------------------------------------------------------------
# P-15 — Reporter runs once, from persisted findings and evidence only
# ---------------------------------------------------------------------------


class TestP15Reporter:
    def test_reporter_uses_persisted_state_and_runs_once(self, store):
        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        rows = _plan(store, task["id"], ["Collect", "Confirm"])

        first, _ = store.claim_next_subtask(task["id"])
        store.record_action(
            first["id"],
            "action-15-a",
            tool="nuclei",
            result={"findings": [{"asset": "api", "type": "header", "severity": "low"}]},
            evidence_refs=["evidence-15-a"],
        )
        store.transition_subtask(
            first["id"],
            SubtaskStatus.FINISHED,
            result={
                "summary": "headers collected",
                "findings": [{"asset": "api", "type": "cors", "severity": "medium"}],
                "evidence_refs": ["evidence-15-b"],
            },
        )

        second, _ = store.claim_next_subtask(task["id"])
        store.transition_subtask(
            second["id"],
            SubtaskStatus.FINISHED,
            result={"summary": "confirmed", "findings": []},
        )
        assert store.find_subtask(rows[1]["id"])["status"] == "finished"
        store.finalize_task(task["id"])

        reporter = Reporter(store)
        first_report = reporter.report(task["id"])
        assert first_report["created"] is True
        body = first_report["body"]
        assert body["finding_count"] == 2
        assert {finding["type"] for finding in body["findings"]} == {"header", "cors"}
        assert body["evidence_refs"] == ["evidence-15-a", "evidence-15-b"]
        assert [entry["title"] for entry in body["subtasks"]] == ["Collect", "Confirm"]

        # A second call returns the same report and does not re-aggregate.
        store.record_action(
            second["id"],
            "action-after-report",
            tool="httpx",
            result={"findings": [{"asset": "late", "type": "late", "severity": "high"}]},
            evidence_refs=["evidence-late"],
        )
        second_report = reporter.report(task["id"])
        assert second_report["created"] is False
        assert second_report["report_id"] == first_report["report_id"]
        assert second_report["body"]["finding_count"] == 2
        assert "evidence-late" not in second_report["body"]["evidence_refs"]


# ---------------------------------------------------------------------------
# P-16 — Memorist returns only tenant-scoped, redacted knowledge
# ---------------------------------------------------------------------------


class TestP16Memorist:
    def test_memorist_redacts_and_enforces_tenant_boundary(self, store):
        tenant_a = str(uuid.uuid4())
        tenant_b = str(uuid.uuid4())
        engagement_a = _create_engagement(tenant_a)
        engagement_b = _create_engagement(tenant_b)
        memorist = Memorist(store)

        stored = memorist.remember(
            engagement_a,
            "Admin panel at /admin; password=hunter2; api_key=sk-live-1234567890",
            kind="credential_note",
        )
        assert stored["redacted"] is True
        assert stored["tenant_scoped"] is True
        assert stored["redactions"] >= 2

        recalled_a = memorist.recall(engagement_a, query="Admin panel")
        assert len(recalled_a) == 1
        assert "hunter2" not in recalled_a[0]["summary"]
        assert "sk-live" not in recalled_a[0]["summary"]
        assert "[REDACTED]" in recalled_a[0]["summary"]

        # Same store, different tenant: nothing leaks.
        assert memorist.recall(engagement_b) == []
        assert store.search_memory(tenant_b) == []
        assert len(store.search_memory(tenant_a)) == 1

        # An engagement with no tenant fails closed rather than sharing memory.
        no_tenant = _create_engagement(None)
        assert memorist.recall(no_tenant) == []


# ---------------------------------------------------------------------------
# P-17 — unresolved failed/skipped subtasks block task success
# ---------------------------------------------------------------------------


class TestP17Resolution:
    def test_failed_subtask_needs_an_explicit_resolution(self, store):
        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        _plan(store, task["id"], ["fails", "finishes"])

        failing, _ = store.claim_next_subtask(task["id"])
        store.transition_subtask(
            failing["id"],
            SubtaskStatus.FAILED,
            result={"summary": "blocked"},
            last_error="target refused all connections",
        )
        finishing, _ = store.claim_next_subtask(task["id"])
        store.transition_subtask(
            finishing["id"], SubtaskStatus.FINISHED, result={"summary": "done"}
        )

        with pytest.raises(TaskCompletionError):
            store.finalize_task(task["id"])
        assert store.find_task(task["id"])["status"] == "running"

        store.resolve_subtask(
            failing["id"], "accepted skip: target owner confirmed the host is retired"
        )
        finished = store.finalize_task(task["id"])
        assert finished["status"] == "finished"

        report = Reporter(store).report(task["id"])
        assert report["body"]["resolutions"] == [
            {
                "subtask_id": str(failing["id"]),
                "resolution": "accepted skip: target owner confirmed the host is retired",
            }
        ]

    def test_skipped_subtask_without_resolution_blocks_completion(self, store):
        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        _plan(store, task["id"], ["skip me"])
        subtask, _ = store.claim_next_subtask(task["id"])
        store.transition_subtask(
            subtask["id"], SubtaskStatus.SKIPPED, last_error="out of budget"
        )
        with pytest.raises(TaskCompletionError):
            store.finalize_task(task["id"])
        store.resolve_subtask(subtask["id"], "budget exhausted, accepted by operator")
        assert store.finalize_task(task["id"])["status"] == "finished"


# ---------------------------------------------------------------------------
# Contract guards that are cheap to assert and keep the hierarchy honest
# ---------------------------------------------------------------------------


class TestDelegationContract:
    def test_task_and_subtask_models_expose_the_persisted_hierarchy(self, store):
        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        rows = _plan(store, task["id"], ["one"])
        from agent.delegation.models import Subtask, Task

        assert Task.from_row(task).engagement_id == engagement_id
        assert Subtask.from_row(rows[0]).task_id == task["id"]
        assert Subtask.from_row(rows[0]).terminal is False

    def test_hierarchical_delegation_flag_is_wired(self, monkeypatch):
        from orchestrator_pkg.planning.flags import hierarchical_delegation_mode

        monkeypatch.setenv("ARGUS_HIERARCHICAL_DELEGATION", "shadow")
        assert hierarchical_delegation_mode() == "shadow"
        monkeypatch.setenv("ARGUS_HIERARCHICAL_DELEGATION", "on")
        assert hierarchical_delegation_mode() == "on"
        monkeypatch.setenv("ARGUS_HIERARCHICAL_DELEGATION", "nonsense")
        with pytest.raises(ValueError):
            hierarchical_delegation_mode()


# ---------------------------------------------------------------------------
# Review hardening — contracts that were too permissive on a fresh read
# ---------------------------------------------------------------------------


class TestReviewHardening:
    def test_repeated_terminal_transition_cannot_rewrite_result(self, store):
        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        _plan(store, task["id"], ["only step"])
        completed = _finish_current(store, task["id"])

        with pytest.raises(InvalidTransition):
            store.transition_subtask(
                completed["id"],
                SubtaskStatus.FINISHED,
                result={"summary": "rewritten evidence"},
            )
        assert (
            store.find_subtask(completed["id"])["result"]["summary"]
            == "done only step"
        )

    def test_finish_requires_a_persisted_result(self, store):
        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        _plan(store, task["id"], ["only step"])
        subtask, _ = store.claim_next_subtask(task["id"])

        with pytest.raises(DelegationError):
            store.transition_subtask(subtask["id"], SubtaskStatus.FINISHED)
        assert store.find_subtask(subtask["id"])["status"] == "running"

    def test_failure_requires_an_explicit_reason(self, store):
        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        _plan(store, task["id"], ["only step"])
        subtask, _ = store.claim_next_subtask(task["id"])

        with pytest.raises(DelegationError):
            store.transition_subtask(subtask["id"], SubtaskStatus.FAILED)
        assert store.find_subtask(subtask["id"])["status"] == "running"

    def test_question_and_answer_survive_resume(self, store):
        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        _plan(store, task["id"], ["needs input"])
        worker = TaskWorker(store, RecordingExecutor())
        subtask, _ = store.claim_next_subtask(task["id"])

        worker.pause_for_input(subtask["id"], "Which role?")
        worker.resume_subtask(subtask["id"], "read-only")

        result = store.find_subtask(subtask["id"])["result"]
        assert result["question"] == "Which role?"
        assert result["operator_input"] == "read-only"

    def test_resolved_skip_or_failure_unblocks_dependents(self, store):
        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        rows = store.insert_plan(
            task["id"],
            [
                SubtaskDraft(title="first", description="first"),
                SubtaskDraft(
                    title="second", description="second", depends_on=("first",)
                ),
            ],
        )
        first, _ = store.claim_next_subtask(task["id"])
        store.transition_subtask(
            first["id"], SubtaskStatus.SKIPPED, last_error="no credentials"
        )
        blocked, reason = store.claim_next_subtask(task["id"])
        assert blocked is None
        assert reason == "dependency_blocked"

        store.resolve_subtask(first["id"], "operator accepted the skip")
        second, reason = store.claim_next_subtask(task["id"])
        assert reason == "started"
        assert second["id"] == rows[1]["id"]

    def test_generator_clamp_rejects_dependency_on_a_clamped_draft(self):
        raw = [
            {"title": "probe", "description": "probe", "depends_on": [16]}
        ]
        raw += [
            {"title": f"filler {index}", "description": "filler"}
            for index in range(2, 16)
        ]
        raw.append({"title": "prereq", "description": "prerequisite"})

        with pytest.raises(PlanValidationError):
            validate_generated_plan(raw, over_limit="clamp")

    def test_patch_rejects_removing_a_prerequisite(self, store):
        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        rows = store.insert_plan(
            task["id"],
            [
                SubtaskDraft(title="first", description="first"),
                SubtaskDraft(
                    title="second", description="second", depends_on=("first",)
                ),
            ],
        )

        with pytest.raises(PatchValidationError):
            apply_patch(
                plan_items(rows),
                [{"op": "REMOVE", "subtask_id": rows[0]["id"]}],
            )

    def test_patch_add_with_unknown_dependency_is_rejected(self, store):
        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        rows = _plan(store, task["id"], ["only"])

        with pytest.raises(PatchValidationError):
            apply_patch(
                plan_items(rows),
                [
                    {
                        "op": "ADD",
                        "title": "new work",
                        "description": "new work",
                        "depends_on": ["ghost"],
                    }
                ],
            )

    def test_apply_plan_rejects_another_tasks_subtask(self, store):
        engagement_id = _create_engagement()
        task_a = _task(store, engagement_id, "A")
        task_b = _task(store, engagement_id, "B")
        rows_a = _plan(store, task_a["id"], ["A only"])
        _plan(store, task_b["id"], ["B only"])

        with pytest.raises(PatchValidationError):
            store.apply_plan(
                task_b["id"],
                plan_items(rows_a),
                trigger_subtask_id=None,
                rationale="cross-task write",
                operations=[],
            )

        assert store.find_subtasks(task_a["id"])[0]["title"] == "A only"
        assert store.find_subtasks(task_b["id"])[0]["title"] == "B only"

    def test_apply_plan_rejects_rewriting_completed_evidence(self, store):
        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        _plan(store, task["id"], ["completed", "remaining"])
        completed = _finish_current(store, task["id"])
        items = plan_items(store.find_subtasks(task["id"]))
        items[0] = replace(items[0], title="rewritten")

        with pytest.raises(PatchValidationError):
            store.apply_plan(
                task["id"],
                items,
                trigger_subtask_id=completed["id"],
                rationale="rewrite evidence",
                operations=[],
            )
        assert store.find_subtask(completed["id"])["title"] == "completed"

    def test_finished_task_plan_is_immutable(self, store):
        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        _plan(store, task["id"], ["only"])
        _finish_current(store, task["id"])
        store.finalize_task(task["id"])
        items = plan_items(store.find_subtasks(task["id"]))
        items.append(
            PlanItem(id="new:1", title="late work", description="late", is_new=True)
        )

        with pytest.raises(PatchValidationError):
            store.apply_plan(
                task["id"],
                items,
                trigger_subtask_id=None,
                rationale="late add",
                operations=[{"op": "ADD", "title": "late work"}],
            )
        assert len(store.find_subtasks(task["id"])) == 1

    def test_refiner_can_grow_completed_history_past_fifteen(self, store):
        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        _plan(store, task["id"], [f"step {index}" for index in range(1, 16)])
        completed = None
        for _ in range(10):
            completed = _finish_current(store, task["id"])

        operations = [
            {"op": "ADD", "title": f"extra {index}", "description": "extra"}
            for index in range(1, 11)
        ]
        outcome = RefinerService(
            store, ScriptedRefiner([operations])
        ).refine_after(task["id"], completed["id"])

        assert outcome["applied"] is True
        rows = store.find_subtasks(task["id"])
        assert len(rows) == 25
        assert sum(
            1 for row in rows if row["status"] in ("created", "running", "waiting")
        ) == MAX_ACTIVE_SUBTASKS

    def test_repeated_run_is_idempotent(self, store):
        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        _plan(store, task["id"], ["only"])
        worker = TaskWorker(
            store, RecordingExecutor(), reporter=Reporter(store)
        )

        first = worker.run(task["id"])
        second = worker.run(task["id"])

        assert first["status"] == "task_finished"
        assert second["status"] == "task_finished"
        assert second["task"]["status"] == "finished"
        assert second["report"]["report_id"] == first["report"]["report_id"]

    def test_worker_records_an_executor_failure_as_failed(self, store):
        class BoomExecutor:
            def execute(self, _request):
                raise RuntimeError("tool crashed")

        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        _plan(store, task["id"], ["explode"])

        outcome = TaskWorker(store, BoomExecutor()).step(task["id"])

        assert outcome["status"] == "failed"
        subtask = store.find_subtasks(task["id"])[0]
        assert subtask["status"] == "failed"
        assert "tool crashed" in subtask["last_error"]
        assert store.find_task(task["id"])["status"] == "running"

    def test_insert_plan_rejects_duplicate_titles_and_self_dependency(self, store):
        engagement_id = _create_engagement()
        duplicate_task = _task(store, engagement_id)

        with pytest.raises(PatchValidationError):
            store.insert_plan(
                duplicate_task["id"],
                [
                    SubtaskDraft(title="same work", description="a"),
                    SubtaskDraft(title="Same work", description="b"),
                ],
            )
        assert store.find_subtasks(duplicate_task["id"]) == []

        self_task = _task(store, engagement_id)
        with pytest.raises(PatchValidationError):
            store.insert_plan(
                self_task["id"],
                [SubtaskDraft(title="loop", description="loop", depends_on=("loop",))],
            )
        assert store.find_subtasks(self_task["id"]) == []

    def test_memorist_rejects_an_unscoped_engagement(self, store):
        engagement_id = _create_engagement(None)
        with pytest.raises(DelegationError):
            Memorist(store).remember(engagement_id, "useful but unscoped fact")

    def test_primary_rejects_non_object_specialist_findings(self):
        registry = SpecialistRegistry()
        registry.register(
            "pentester",
            {"http"},
            EchoSpecialist(
                {"summary": "probe", "findings": ["bare string, not a finding"]}
            ),
        )
        with pytest.raises(DelegationError):
            PrimaryAgent(registry).handle(
                {"id": "s", "title": "probe", "description": "probe"},
                capabilities={"http"},
            )

    def test_completion_condition_is_persisted(self, store):
        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        rows = store.insert_plan(
            task["id"],
            [
                SubtaskDraft(
                    title="verify login",
                    description="verify login",
                    completion_condition="a 200 response from /login",
                )
            ],
        )

        assert rows[0]["completion_condition"] == "a 200 response from /login"
        assert (
            plan_items(rows)[0].completion_condition
            == "a 200 response from /login"
        )

    def test_apply_plan_rejects_editing_a_running_subtask(self, store):
        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        _plan(store, task["id"], ["running", "remaining"])
        store.claim_next_subtask(task["id"])
        items = plan_items(store.find_subtasks(task["id"]))
        items[0] = replace(items[0], title="changed while running")

        with pytest.raises(PatchValidationError):
            store.apply_plan(
                task["id"],
                items,
                trigger_subtask_id=None,
                rationale="edit running work",
                operations=[],
            )
        assert store.find_subtasks(task["id"])[0]["title"] == "running"

    def test_new_item_cannot_bypass_the_active_cap_with_a_terminal_status(self, store):
        engagement_id = _create_engagement()
        task = _task(store, engagement_id)
        rows = _plan(
            store,
            task["id"],
            [f"step {index}" for index in range(1, MAX_ACTIVE_SUBTASKS + 1)],
        )
        items = plan_items(rows)
        items.append(
            PlanItem(
                id="new:1",
                title="overflow",
                description="overflow",
                status=SubtaskStatus.FINISHED,
                is_new=True,
            )
        )

        with pytest.raises(PatchValidationError):
            store.apply_plan(
                task["id"],
                items,
                trigger_subtask_id=None,
                rationale="bypass cap",
                operations=[],
            )
        assert len(store.find_subtasks(task["id"])) == MAX_ACTIVE_SUBTASKS

    def test_reconcile_rejects_an_unknown_task(self, store):
        with pytest.raises(DelegationError):
            TaskWorker(store, RecordingExecutor()).reconcile(str(uuid.uuid4()))
