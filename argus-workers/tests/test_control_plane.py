"""Fact-and-intent control plane conformance tests (C-01…C-22).

DB-backed tests run against PostgreSQL with migration 040 applied and are
skipped when DATABASE_URL is unreachable.
"""

from __future__ import annotations

import os
import random
import uuid

import psycopg2
import pytest

from control_plane import (
    ControlPlaneDispatcher,
    LateResult,
    NotLeader,
    PostgresControlPlaneStore,
    ProtocolError,
    choose_worker,
    parse_bootstrap_conclude,
    parse_explore_result,
    parse_reason_result,
)
from control_plane.scheduler import WorkerView
from database.connection import get_db
from database.graph_ownership import GraphOwnershipError
from database.migrations.runner import run_migrations

DB_URL = os.getenv("DATABASE_URL") or os.getenv("TEST_DATABASE_URL")


def _available() -> bool:
    if not DB_URL:
        return False
    try:
        psycopg2.connect(DB_URL, connect_timeout=3)
        return True
    except Exception:
        return False


DB_AVAILABLE = _available()
_SCHEMA_READY = False
pytestmark = pytest.mark.skipif(
    not DB_AVAILABLE, reason="DATABASE_URL not reachable in this environment"
)


class FakeRunner:
    def __init__(
        self,
        *,
        bootstrap=None,
        bootstrap_conclude=None,
        reason=None,
        explore=None,
        explore_conclude=None,
    ) -> None:
        self.bootstrap_result = bootstrap
        self.bootstrap_conclude_result = bootstrap_conclude
        self.reason_result = reason
        self.explore_result = explore
        self.explore_conclude_result = explore_conclude
        self.calls: list[str] = []

    def supports(self, task_type: str) -> bool:
        return True

    def _raise_or(self, value):
        if isinstance(value, Exception):
            raise value
        return value

    def bootstrap(self, job, *, conclude=False):
        self.calls.append("bootstrap_conclude" if conclude else "bootstrap")
        return self._raise_or(
            self.bootstrap_conclude_result if conclude else self.bootstrap_result
        )

    def reason(self, job):
        self.calls.append("reason")
        return self._raise_or(self.reason_result)

    def explore(self, job, *, conclude=False):
        self.calls.append("explore_conclude" if conclude else "explore")
        return self._raise_or(
            self.explore_conclude_result if conclude else self.explore_result
        )


@pytest.fixture(scope="module", autouse=True)
def _schema():
    global _SCHEMA_READY
    if DB_AVAILABLE and not _SCHEMA_READY:
        run_migrations()
        _SCHEMA_READY = True


@pytest.fixture()
def store():
    return PostgresControlPlaneStore()


def _engage(status: str = "running") -> str:
    engagement_id = str(uuid.uuid4())
    with get_db().connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO engagements (id, target, status) VALUES (%s, %s, %s)",
            (engagement_id, f"https://{engagement_id[:8]}.example", status),
        )
        cur.close()
    return engagement_id


def _node(store, engagement_id, kind, payload, *, state="open"):
    return store.graph.create_node(
        engagement_id, kind, payload=payload, state=state, origin="test"
    )


def _goal(store, engagement_id):
    return _node(store, engagement_id, "goal", {"objective": "prove the target"})


def _fact(store, engagement_id, text="an observed fact"):
    return _node(store, engagement_id, "fact", {"summary": text})


def _intent(store, engagement_id, text="explore login"):
    return _node(store, engagement_id, "intent", {"objective": text})


def _hint(store, engagement_id, text="try the login page"):
    return _node(store, engagement_id, "hint", {"text": text})


def _counts(store, engagement_id):
    return store.graph_counts(engagement_id)


def _all_nodes(store, engagement_id):
    return store.graph.find_nodes_by_engagement(engagement_id, limit=500)


SUCCESS_EXECUTE = {
    "accepted": True,
    "data": {"fact": {"description": "login page exists"}, "complete": {"description": "goal met"}},
}


def test_c01_bootstrap_requires_compatible_worker_or_reservation(store):
    engagement_id = _engage()
    _goal(store, engagement_id)
    assert store.bootstrap_eligible(engagement_id)
    runner = FakeRunner(bootstrap=SUCCESS_EXECUTE)
    dispatcher = ControlPlaneDispatcher(store, runner)
    assert choose_worker([], "bootstrap") is None
    assert store.bootstrap_row(engagement_id) is None
    worker = f"w-bootstrap-{engagement_id[:8]}"
    store.register_worker(worker, ["bootstrap"])
    assert dispatcher.tick(engagement_id) == "bootstrap"
    assert store.bootstrap_row(engagement_id)["status"] == "completed"


def test_c02_execute_writes_one_fact_then_completes_goal(store):
    engagement_id = _engage()
    goal = _goal(store, engagement_id)
    store.register_worker("w", ["bootstrap"])
    dispatcher = ControlPlaneDispatcher(store, FakeRunner(bootstrap=SUCCESS_EXECUTE))
    dispatcher.run_bootstrap(engagement_id, "w")
    assert _counts(store, engagement_id)["facts"] == 1
    assert store.graph.find_node_by_id(goal["id"])["state"] == "concluded"
    dispatcher.run_bootstrap(engagement_id, "w")
    assert _counts(store, engagement_id)["facts"] == 1


def test_c03_execute_timeout_conclude_writes_fact_only(store):
    engagement_id = _engage()
    goal = _goal(store, engagement_id)
    store.register_worker("w", ["bootstrap"])
    runner = FakeRunner(
        bootstrap=TimeoutError("timed out"),
        bootstrap_conclude={
            "accepted": True,
            "data": {"fact": {"description": "partial evidence"}},
        },
    )
    result = ControlPlaneDispatcher(store, runner).run_bootstrap(engagement_id, "w")
    assert result["status"] == "succeeded"
    assert _counts(store, engagement_id)["facts"] == 1
    assert store.graph.find_node_by_id(goal["id"])["state"] == "open"
    assert store.reason_trigger(engagement_id) == "initial"


def test_c04_conclude_cannot_complete_the_goal(store):
    engagement_id = _engage()
    goal = _goal(store, engagement_id)
    store.register_worker("w", ["bootstrap"])
    bad = {
        "accepted": True,
        "data": {
            "fact": {"description": "evidence"},
            "complete": {"description": "done"},
        },
    }
    with pytest.raises(ProtocolError):
        parse_bootstrap_conclude(bad)
    runner = FakeRunner(bootstrap=TimeoutError("timeout"), bootstrap_conclude=bad)
    result = ControlPlaneDispatcher(store, runner).run_bootstrap(engagement_id, "w")
    assert result["status"] == "failed"
    assert _counts(store, engagement_id)["facts"] == 0
    assert store.graph.find_node_by_id(goal["id"])["state"] == "open"
    assert store.bootstrap_row(engagement_id)["status"] == "released"


def test_c05_both_stages_fail_releases_reservation(store):
    engagement_id = _engage()
    _goal(store, engagement_id)
    store.register_worker("w", ["bootstrap"])
    runner = FakeRunner(
        bootstrap=TimeoutError("timeout"), bootstrap_conclude=TimeoutError("timeout")
    )
    ControlPlaneDispatcher(store, runner).run_bootstrap(engagement_id, "w")
    row = store.bootstrap_row(engagement_id)
    assert row["status"] == "released"
    assert _counts(store, engagement_id)["facts"] == 0
    reserved = store.graph.find_node_by_id(row["reserved_intent_node_id"])
    assert reserved["state"] == "cancelled"


def _reason_payload(**data):
    return {"accepted": True, "data": data}


def test_c06_complete_and_intents_conflict_writes_nothing(store):
    engagement_id = _engage()
    _goal(store, engagement_id)
    fact = _fact(store, engagement_id)
    before = len(_all_nodes(store, engagement_id))
    payload = _reason_payload(
        complete={"description": "done", "from": [str(fact["id"])]},
        intents=[{"description": "more", "from": [str(fact["id"])]}],
    )
    with pytest.raises(ProtocolError):
        parse_reason_result(
            payload,
            valid_fact_ids=[str(fact["id"])],
            goal_ids=[],
            open_intent_count=0,
            max_intents=5,
        )
    assert len(_all_nodes(store, engagement_id)) == before


def test_c07_unknown_fact_id_is_rejected(store):
    engagement_id = _engage()
    _fact(store, engagement_id)
    payload = _reason_payload(
        intents=[{"description": "new direction", "from": [str(uuid.uuid4())]}]
    )
    with pytest.raises(ProtocolError):
        parse_reason_result(
            payload, valid_fact_ids=[], goal_ids=[], open_intent_count=0
        )
    assert _counts(store, engagement_id)["open_intents"] == 0


def test_c08_empty_reason_with_no_open_intents_is_invalid(store):
    with pytest.raises(ProtocolError):
        parse_reason_result(
            {"accepted": True, "data": {}},
            valid_fact_ids=[],
            goal_ids=[],
            open_intent_count=0,
        )


def test_c09_intents_are_bounded_and_truncation_recorded(store):
    engagement_id = _engage()
    fact = _fact(store, engagement_id)
    payload = _reason_payload(
        intents=[
            {"description": f"direction {index}", "from": [str(fact["id"])]}
            for index in range(5)
        ]
    )
    decision = parse_reason_result(
        payload,
        valid_fact_ids=[str(fact["id"])],
        open_intent_count=0,
        max_intents=3,
    )
    assert decision.truncated and decision.received_intent_count == 5
    result = store.apply_reason(engagement_id, decision)
    assert len(result["created"]) == 3


def test_c10_only_one_reason_lease(store):
    engagement_id = _engage()
    first = store.acquire_lease(engagement_id, "reason", "owner-a")
    second = store.acquire_lease(engagement_id, "reason", "owner-b")
    assert first is not None and second is None


def test_c11_failed_reason_does_not_immediately_retrigger(store):
    engagement_id = _engage()
    _goal(store, engagement_id)
    _fact(store, engagement_id)
    store.register_worker("w", ["reason"])
    dispatcher = ControlPlaneDispatcher(
        store, FakeRunner(reason=RuntimeError("provider exploded"))
    )
    assert dispatcher.run_reason(engagement_id, "w") == "failed"
    assert store.reason_trigger(engagement_id) is None


def test_c12_fact_or_hint_growth_triggers_reason(store):
    engagement_id = _engage()
    _goal(store, engagement_id)
    store.record_reason_checkpoint(engagement_id, "noop")
    assert store.reason_trigger(engagement_id) is None
    _fact(store, engagement_id, "new fact")
    assert store.reason_trigger(engagement_id) == "facts_increased"
    store.record_reason_checkpoint(engagement_id, "noop")
    _hint(store, engagement_id, "new hint")
    assert store.reason_trigger(engagement_id) == "hints_increased"


def test_c13_last_open_intent_closing_triggers_reason(store):
    engagement_id = _engage()
    _goal(store, engagement_id)
    intent = _intent(store, engagement_id)
    store.record_reason_checkpoint(engagement_id, "intents")
    assert store.reason_trigger(engagement_id) is None
    store.graph.update_node_state(intent["id"], "concluded")
    assert store.reason_trigger(engagement_id) == "intents_exhausted"


def test_c14_explore_receives_exactly_one_intent(store):
    engagement_id = _engage()
    _intent(store, engagement_id, "first")
    _intent(store, engagement_id, "second")
    claim = store.claim_explore(engagement_id, "worker-1")
    with get_db().connection(commit=False) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM control_plane_tasks WHERE engagement_id = %s",
            (engagement_id,),
        )
        assert cur.fetchone()[0] == 1
        cur.close()
    assert claim["job"]["intent"]["objective"] in {"first", "second"}
    assert "claim_token" not in claim["job"] and "lease_token" not in claim["job"]
    second = store.claim_explore(engagement_id, "worker-2")
    assert second["job"]["intent"]["id"] != claim["job"]["intent"]["id"]


def test_c15_explore_writes_one_conclusion_fact(store):
    engagement_id = _engage()
    _goal(store, engagement_id)
    intent = _intent(store, engagement_id)
    claim = store.claim_explore(engagement_id, "worker-1")
    result = store.conclude_explore(
        claim["task"]["id"], "login page accepts default credentials"
    )
    assert result["status"] == "succeeded"
    facts = [row for row in _all_nodes(store, engagement_id) if row["kind"] == "fact"]
    assert len(facts) == 1
    assert store.graph.find_node_by_id(intent["id"])["state"] == "concluded"


def test_c16_malformed_explore_then_conclude_writes_once(store):
    engagement_id = _engage()
    _intent(store, engagement_id)
    store.register_worker("w", ["explore"])
    runner = FakeRunner(
        explore={"accepted": True, "data": {}},
        explore_conclude={
            "accepted": True,
            "data": {"description": "concluded evidence"},
        },
    )
    result = ControlPlaneDispatcher(store, runner).run_explore(engagement_id, "w")
    assert result["status"] == "succeeded"
    assert _counts(store, engagement_id)["facts"] == 1


def test_c17_cancellation_and_lost_lease_block_conclusion(store):
    engagement_id = _engage()
    _intent(store, engagement_id)
    claim = store.claim_explore(engagement_id, "worker-1")
    store.cancel_task(claim["task"]["id"], "operator cancelled")
    with pytest.raises(LateResult):
        store.conclude_explore(claim["task"]["id"], "must not be written")
    assert _counts(store, engagement_id)["facts"] == 0

    second = store.claim_explore(engagement_id, "worker-2")
    with get_db().connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE graph_nodes SET lease_expires_at = NOW() - INTERVAL '1 second' "
            "WHERE id = %s",
            (second["task"]["intent_node_id"],),
        )
        cur.close()
    with pytest.raises(LateResult):
        store.conclude_explore(second["task"]["id"], "late")
    assert _counts(store, engagement_id)["facts"] == 0


def test_c18_workers_have_no_write_path_or_credentials(store):
    engagement_id = _engage()
    _intent(store, engagement_id)
    claim = store.claim_explore(engagement_id, "worker-1")
    job = claim["job"]
    assert not {"claim_token", "lease_token", "database_url", "dsn"} & set(job)
    with pytest.raises(GraphOwnershipError):
        store.graph.repository.create_node(
            engagement_id, "fact", payload={"summary": "forged"}
        )


def test_c19_stopped_engagement_cancels_and_rejects_late_results(store):
    engagement_id = _engage()
    _intent(store, engagement_id)
    claim = store.claim_explore(engagement_id, "worker-1")
    with get_db().connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE engagements SET status = 'completed' WHERE id = %s",
            (engagement_id,),
        )
        cur.close()
    store.register_worker("w", ["explore"])
    dispatcher = ControlPlaneDispatcher(store, FakeRunner())
    assert dispatcher.tick(engagement_id) == "cancelled"
    assert store.get_task(claim["task"]["id"])["status"] == "cancelled"
    with pytest.raises(LateResult):
        store.conclude_explore(claim["task"]["id"], "late result")
    assert _counts(store, engagement_id)["facts"] == 0


def test_c20_scheduler_skips_full_and_unhealthy_workers(store):
    engagement_id = _engage()
    _intent(store, engagement_id)
    full = f"full-{engagement_id[:8]}"
    sick = f"sick-{engagement_id[:8]}"
    healthy = f"healthy-{engagement_id[:8]}"
    store.register_worker(full, ["explore"], max_running=1)
    store.register_worker(sick, ["explore"], healthy=False)
    store.register_worker(healthy, ["explore"], priority=5)
    claim = store.claim_explore(engagement_id, full)
    assert claim is not None
    store.start_task(engagement_id, "explore", full)
    workers = [
        WorkerView(
            worker_id=row["worker_id"],
            task_types=frozenset(row["task_types"]),
            max_running=row["max_running"],
            running=row["running"],
            priority=row["priority"],
            healthy=row["healthy"],
            unavailable_until=row["unavailable_until"],
        )
        for row in store.list_workers()
    ]
    chosen = choose_worker(
        [worker for worker in workers if worker.worker_id in {full, sick, healthy}],
        "explore",
        rng=random.Random(7),
    )
    assert chosen.worker_id == healthy


def test_c21_one_dispatcher_leader_per_engagement(store):
    engagement_id = _engage()
    first = ControlPlaneDispatcher(store, FakeRunner(), owner="dispatcher-a")
    first.acquire_leadership(engagement_id)
    second = ControlPlaneDispatcher(store, FakeRunner(), owner="dispatcher-b")
    with pytest.raises(NotLeader):
        second.acquire_leadership(engagement_id)


def test_c22_extra_fields_rejected_and_legacy_alias_opt_in(store):
    fact_id = str(uuid.uuid4())
    with pytest.raises(ProtocolError):
        parse_reason_result(
            {"accepted": True, "data": {"intents": []}, "note": "extra"},
            valid_fact_ids=[fact_id],
            open_intent_count=0,
        )
    with pytest.raises(ProtocolError):
        parse_explore_result({"accepted": True, "data": {"description": "x", "fact": {}}})
    legacy = {"accepted": True, "data": {"intent": {"description": "one", "from": [fact_id]}}}
    with pytest.raises(ProtocolError):
        parse_reason_result(
            legacy, valid_fact_ids=[fact_id], open_intent_count=0
        )
    decision = parse_reason_result(
        legacy,
        valid_fact_ids=[fact_id],
        open_intent_count=0,
        allow_legacy_intent=True,
    )
    assert decision.kind == "intents" and decision.intents[0].description == "one"


def test_bootstrap_contract_violation_runs_conclude(store):
    engagement_id = _engage()
    _goal(store, engagement_id)
    runner = FakeRunner(
        bootstrap={"accepted": True, "data": {}},
        bootstrap_conclude={
            "accepted": True,
            "data": {"fact": {"description": "fallback evidence"}},
        },
    )
    result = ControlPlaneDispatcher(store, runner).run_bootstrap(engagement_id, "w-cv")
    assert result["status"] == "succeeded"
    assert runner.calls == ["bootstrap", "bootstrap_conclude"]
    assert _counts(store, engagement_id)["facts"] == 1


def test_bootstrap_crash_does_not_run_conclude(store):
    engagement_id = _engage()
    goal = _goal(store, engagement_id)
    runner = FakeRunner(
        bootstrap=RuntimeError("executor crashed"),
        bootstrap_conclude={
            "accepted": True,
            "data": {"fact": {"description": "must not be used"}},
        },
    )
    result = ControlPlaneDispatcher(store, runner).run_bootstrap(engagement_id, "w-crash")
    assert result["status"] == "failed"
    assert runner.calls == ["bootstrap"]
    assert _counts(store, engagement_id)["facts"] == 0
    assert store.graph.find_node_by_id(goal["id"])["state"] == "open"
    assert store.bootstrap_row(engagement_id)["status"] == "released"


def test_explore_crash_does_not_run_conclude(store):
    engagement_id = _engage()
    intent = _intent(store, engagement_id)
    runner = FakeRunner(
        explore=RuntimeError("executor crashed"),
        explore_conclude={
            "accepted": True,
            "data": {"description": "must not be used"},
        },
    )
    result = ControlPlaneDispatcher(store, runner).run_explore(engagement_id, "w-crash")
    assert result == "failed"
    assert runner.calls == ["explore"]
    assert _counts(store, engagement_id)["facts"] == 0
    assert store.graph.find_node_by_id(intent["id"])["state"] == "open"
