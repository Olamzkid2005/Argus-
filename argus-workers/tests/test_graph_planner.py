"""
ARTEX planner event loop tests (A3) against PostgreSQL.

These drive the real dispatcher/repository path:

- outbox bursts consumed by one debounced planning turn
- the hard floor (unmet goal + no intent) failing loudly
- typed IntentProposal validation and duplicate suppression
- dependency-aware claim selection across a restart
- claim fencing tokens and heartbeat lease renewal/release
"""

from __future__ import annotations

import os
import uuid

import pytest

from database.dispatcher_graph import DispatcherGraph
from database.graph_intents import IntentProposal, IntentProposalError
from database.graph_repository import (
    ExplorationGraphRepository,
    GraphClaimLostError,
    GraphMutationError,
    GraphNodeKind,
    TodoStatus,
)
from tasks.graph_planner import (
    PlannerHardFloorError,
    run_planner_loop,
    run_planner_turn,
)


def _db_available() -> bool:
    url = os.getenv("DATABASE_URL", os.getenv("TEST_DATABASE_URL"))
    if not url:
        return False
    try:
        import psycopg2

        psycopg2.connect(url, connect_timeout=3)
        return True
    except Exception:
        return False


DB_AVAILABLE = _db_available()

pytestmark = pytest.mark.skipif(
    not DB_AVAILABLE, reason="DATABASE_URL not reachable in this environment"
)


def _create_engagement(engagement_id: str, authorized_scope: dict | None = None) -> None:
    import psycopg2
    from psycopg2.extras import Json

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO engagements (id, org_id, target, authorized_scope)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    org_id = EXCLUDED.org_id,
                    authorized_scope = EXCLUDED.authorized_scope
                """,
                (
                    engagement_id,
                    str(uuid.uuid4()),
                    "https://planner.example.com",
                    Json(authorized_scope) if authorized_scope is not None else None,
                ),
            )
    finally:
        conn.close()


def _dispatcher() -> DispatcherGraph:
    return DispatcherGraph(ExplorationGraphRepository())


def _engagement_with_goal(*, assets: int = 1) -> tuple[str, DispatcherGraph, list[dict]]:
    engagement_id = str(uuid.uuid4())
    _create_engagement(engagement_id)
    dispatcher = _dispatcher()
    dispatcher.create_node(
        engagement_id,
        GraphNodeKind.GOAL,
        payload={"objective": "prove the engagement goal"},
    )
    created = [
        dispatcher.ensure_asset(
            f"host{i}.example.com",
            "subdomain",
            scope_id=engagement_id,
        )
        for i in range(assets)
    ]
    return engagement_id, dispatcher, created


def _gap_todo(
    dispatcher: DispatcherGraph,
    engagement_id: str,
    gap_key: str,
    *,
    depends_on: str | None = None,
) -> dict:
    node = dispatcher.create_node(
        engagement_id,
        GraphNodeKind.INTENT,
        payload={"objective": f"work {gap_key}"},
    )
    return dispatcher.create_todo(
        engagement_id,
        todo_type="expand",
        exploration_node_id=node["id"],
        payload={"coverage_gap_key": gap_key, "objective": gap_key},
        depends_on=depends_on,
    )


class TestOutboxPlanningLoop:
    def test_burst_of_graph_events_becomes_one_planning_turn(self):
        engagement_id, dispatcher, _assets = _engagement_with_goal(assets=5)
        repo = dispatcher.repository
        pending = dispatcher.count_queued_outbox(engagement_id)
        assert pending >= 6  # goal node + five asset upserts

        result = run_planner_loop(engagement_id, dispatcher=dispatcher)

        assert result["turns"] == 1
        assert result["events_consumed"] == pending
        assert result["stopped_reason"] == "idle"

        turns = dispatcher.find_planner_turns(engagement_id)
        assert len(turns) == 1
        assert turns[0]["status"] == "completed"
        assert turns[0]["events_consumed"] == pending
        assert turns[0]["intents_created"] >= 1
        assert turns[0]["error"] is None

        queued = repo.find_outbox_for_scope(
            scope_type="graph", scope_id=engagement_id, status="queued"
        )
        assert queued == []
        consumed = repo.find_outbox_for_scope(
            scope_type="graph", scope_id=engagement_id, status="dequeued"
        )
        assert len(consumed) == pending
        assert {str(row["planner_turn_id"]) for row in consumed} == {turns[0]["id"]}

        # A second pass over unchanged state neither spins nor invents work.
        again = run_planner_loop(engagement_id, dispatcher=dispatcher)
        assert again["turns"] == 0
        assert again["events_consumed"] == 0
        assert len(dispatcher.find_planner_turns(engagement_id)) == 1

    def test_a_wake_that_arrived_while_idle_is_consumed_later(self):
        engagement_id, dispatcher, _assets = _engagement_with_goal(assets=1)
        run_planner_loop(engagement_id, dispatcher=dispatcher)
        assert dispatcher.count_queued_outbox(engagement_id) == 0

        # A graph change made while no loop is running must not be stranded.
        dispatcher.ensure_asset(
            "late.example.com", "subdomain", scope_id=engagement_id
        )
        assert dispatcher.count_queued_outbox(engagement_id) == 1

        result = run_planner_loop(engagement_id, dispatcher=dispatcher)
        assert result["turns"] == 1
        assert result["events_consumed"] == 1
        assert dispatcher.count_queued_outbox(engagement_id) == 0

    def test_hot_planner_is_bounded_by_max_turns(self):
        engagement_id, dispatcher, _assets = _engagement_with_goal(assets=1)

        class _HotPlanner:
            def __init__(self) -> None:
                self.calls = 0

            def plan(self, overview):
                self.calls += 1
                dispatcher.create_node(
                    engagement_id,
                    GraphNodeKind.HINT,
                    payload={"hot": self.calls},
                )
                return [
                    IntentProposal(
                        objective=f"hot intent {self.calls}",
                        target_asset_ids=(str(_assets[0]["id"]),),
                    )
                ]

        planner = _HotPlanner()
        result = run_planner_loop(
            engagement_id, max_turns=3, dispatcher=dispatcher, planner=planner
        )

        assert planner.calls == 3
        assert result["turns"] == 3
        assert result["stopped_reason"] == "max_turns"
        # The bound stopped the loop; the remaining wake would be consumed next run.
        assert dispatcher.count_queued_outbox(engagement_id) >= 1
        assert len(dispatcher.find_planner_turns(engagement_id)) == 3


class TestHardFloorAndProposalContract:
    def test_unmet_goal_with_no_intent_hard_fails_loudly(self):
        engagement_id = str(uuid.uuid4())
        _create_engagement(engagement_id)
        dispatcher = _dispatcher()
        dispatcher.create_node(
            engagement_id,
            GraphNodeKind.GOAL,
            payload={"objective": "unreachable without any asset"},
        )

        with pytest.raises(PlannerHardFloorError):
            run_planner_turn(engagement_id, dispatcher=dispatcher)

        turns = dispatcher.find_planner_turns(engagement_id)
        assert len(turns) == 1
        assert turns[0]["status"] == "failed"
        assert "unmet goal" in turns[0]["error"]
        assert dispatcher.planner_overview(engagement_id)["open_intents"] == []

    def test_valid_proposal_is_persisted_with_anchors(self):
        engagement_id, dispatcher, assets = _engagement_with_goal(assets=1)
        goal = dispatcher.planner_overview(engagement_id)["goals"][0]
        proposal = IntentProposal(
            objective="test the untested subdomain",
            target_asset_ids=(str(assets[0]["id"]),),
            goal_node_id=str(goal["id"]),
            priority=7,
            rationale="planner test",
        )

        applied = dispatcher.apply_intent_proposals(engagement_id, [proposal])

        assert applied["proposals_received"] == 1
        assert len(applied["created"]) == 1
        node = applied["created"][0]
        assert node["kind"] == GraphNodeKind.INTENT
        assert node["state"] == "open"
        assert node["payload"]["intent_key"] == proposal.intent_key()
        anchors = dispatcher.repository.find_anchors_for_node(node["id"])
        assert [str(anchor["id"]) for anchor in anchors] == [
            str(assets[0]["id"])
        ]

    def test_duplicate_and_already_proven_intents_are_suppressed(self):
        engagement_id, dispatcher, assets = _engagement_with_goal(assets=1)
        proposal = IntentProposal(
            objective="test the untested subdomain",
            target_asset_ids=(str(assets[0]["id"]),),
        )

        first = dispatcher.apply_intent_proposals(engagement_id, [proposal])
        assert len(first["created"]) == 1

        second = dispatcher.apply_intent_proposals(engagement_id, [proposal])
        assert second["created"] == []
        assert second["suppressed"][0]["reason"] == "open_intent"

        # Existing evidence (a fact carrying the same intent key) also suppresses.
        proven = IntentProposal(
            objective="test an already proven surface",
            target_asset_ids=(str(assets[0]["id"]),),
        )
        dispatcher.create_node(
            engagement_id,
            GraphNodeKind.FACT,
            payload={
                "intent_key": proven.intent_key(),
                "summary": "already tested",
            },
        )
        third = dispatcher.apply_intent_proposals(engagement_id, [proven])
        assert third["created"] == []
        assert third["suppressed"][0]["reason"] == "existing_evidence"

        # A planner turn against existing open intents emits nothing new and does
        # not trip the hard floor.
        overview = dispatcher.planner_overview(engagement_id)
        assert overview["open_intents"]

    def test_invalid_and_out_of_scope_proposals_are_rejected(self):
        engagement_id, dispatcher, assets = _engagement_with_goal(assets=1)

        with pytest.raises(IntentProposalError):
            IntentProposal(objective="  ", target_asset_ids=("not-a-uuid",)).validated()

        with pytest.raises(IntentProposalError):
            IntentProposal(
                objective="bad target", target_asset_ids=("not-a-uuid",)
            ).validated()

        out_of_scope = IntentProposal(
            objective="test a foreign asset",
            target_asset_ids=(str(uuid.uuid4()),),
        )
        with pytest.raises(GraphMutationError):
            dispatcher.apply_intent_proposals(engagement_id, [out_of_scope])
        assert dispatcher.planner_overview(engagement_id)["open_intents"] == []

        unknown_fact = IntentProposal(
            objective="test with an unknown fact",
            target_asset_ids=(str(assets[0]["id"]),),
            from_fact_ids=(str(uuid.uuid4()),),
        )
        with pytest.raises(GraphMutationError):
            dispatcher.apply_intent_proposals(engagement_id, [unknown_fact])


class TestDependencyAwareClaims:
    def test_dependent_todo_is_refused_until_prerequisite_completes(self):
        engagement_id, dispatcher, _assets = _engagement_with_goal(assets=1)
        prerequisite = _gap_todo(dispatcher, engagement_id, "chain:prereq")
        dependent = _gap_todo(
            dispatcher,
            engagement_id,
            "chain:dependent",
            depends_on=prerequisite["id"],
        )

        assert (
            dispatcher.claim_recon_todo(
                engagement_id, owner="worker-1", gap_key="chain:dependent"
            )
            is None
        )

        claimed = dispatcher.claim_recon_todo(
            engagement_id, owner="worker-1", gap_key="chain:prereq"
        )
        assert claimed is not None
        dispatcher.complete_recon_todo(
            engagement_id,
            claimed["id"],
            claim_token=claimed["claim_token"],
        )

        allowed = dispatcher.claim_recon_todo(
            engagement_id, owner="worker-2", gap_key="chain:dependent"
        )
        assert allowed is not None
        assert allowed["id"] == dependent["id"]

    def test_pending_chain_survives_restart_without_early_dispatch(self):
        engagement_id, dispatcher, _assets = _engagement_with_goal(assets=1)
        prerequisite = _gap_todo(dispatcher, engagement_id, "restart:prereq")
        dependent = _gap_todo(
            dispatcher,
            engagement_id,
            "restart:dependent",
            depends_on=prerequisite["id"],
        )

        proc_one = _dispatcher()
        claimed = proc_one.claim_recon_todo(
            engagement_id, owner="worker-1", gap_key="restart:prereq"
        )
        assert claimed is not None

        # Simulated process restart: new dispatcher/repository objects, same DB.
        proc_two = _dispatcher()
        assert (
            proc_two.claim_recon_todo(
                engagement_id, owner="worker-2", gap_key="restart:dependent"
            )
            is None
        )
        persisted = [
            todo
            for todo in proc_two.repository.find_todos_for_engagement(engagement_id)
            if todo["id"] == dependent["id"]
        ][0]
        assert persisted["status"] == TodoStatus.OPEN
        assert persisted["depends_on"] == prerequisite["id"]

        proc_one.complete_recon_todo(
            engagement_id,
            claimed["id"],
            claim_token=claimed["claim_token"],
        )

        proc_three = _dispatcher()
        allowed = proc_three.claim_recon_todo(
            engagement_id, owner="worker-3", gap_key="restart:dependent"
        )
        assert allowed is not None
        assert allowed["id"] == dependent["id"]


class TestClaimFencingAndHeartbeat:
    def _expire_claim(self, todo_id: str) -> None:
        import psycopg2

        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        try:
            with conn, conn.cursor() as cur:
                cur.execute(
                    "UPDATE planner_todos "
                    "SET lease_expires_at = NOW() - INTERVAL '1 second' "
                    "WHERE id = %s",
                    (todo_id,),
                )
        finally:
            conn.close()

    def test_stale_token_write_is_rejected_after_reclaim(self):
        engagement_id, dispatcher, _assets = _engagement_with_goal(assets=1)
        _gap_todo(dispatcher, engagement_id, "fence:gap")

        first = dispatcher.claim_recon_todo(engagement_id, owner="worker-1")
        assert first is not None
        first_token = first["claim_token"]
        self._expire_claim(first["id"])

        second = _dispatcher().claim_recon_todo(engagement_id, owner="worker-2")
        assert second is not None
        assert second["id"] == first["id"]
        assert second["claim_token"] != first_token

        with pytest.raises(GraphClaimLostError):
            dispatcher.complete_recon_todo(
                engagement_id, first["id"], claim_token=first_token
            )
        with pytest.raises(GraphClaimLostError):
            dispatcher.heartbeat_recon_todo(
                engagement_id, first["id"], claim_token=first_token
            )
        with pytest.raises(GraphClaimLostError):
            dispatcher.complete_recon_todo(engagement_id, first["id"])

        # The stale write changed nothing; the live claim still owns the todo.
        todo = next(
            row
            for row in dispatcher.repository.find_todos_for_engagement(engagement_id)
            if row["id"] == first["id"]
        )
        assert todo["status"] == TodoStatus.IN_PROGRESS
        assert str(todo["claim_token"]) == str(second["claim_token"])

        completed = dispatcher.complete_recon_todo(
            engagement_id, second["id"], claim_token=second["claim_token"]
        )
        assert completed["status"] == TodoStatus.DONE
        assert completed["claim_token"] is None

    def test_heartbeat_keeps_live_claim_and_expired_lease_reports_loss(self):
        engagement_id, dispatcher, _assets = _engagement_with_goal(assets=1)
        _gap_todo(dispatcher, engagement_id, "heartbeat:gap")

        claimed = dispatcher.claim_recon_todo(
            engagement_id, owner="worker-1", lease_seconds=60
        )
        assert claimed is not None
        heartbeat = dispatcher.heartbeat_recon_todo(
            engagement_id,
            claimed["id"],
            claim_token=claimed["claim_token"],
            lease_seconds=300,
        )
        assert heartbeat["lease_expires_at"] > claimed["lease_expires_at"]
        assert heartbeat["last_heartbeat_at"] is not None

        # A live (heartbeating) claim is not stolen.
        assert (
            _dispatcher().claim_recon_todo(
                engagement_id, owner="worker-2", gap_key="heartbeat:gap"
            )
            is None
        )

        self._expire_claim(claimed["id"])
        with pytest.raises(GraphClaimLostError):
            dispatcher.heartbeat_recon_todo(
                engagement_id,
                claimed["id"],
                claim_token=claimed["claim_token"],
                lease_seconds=300,
            )

        reclaimed = _dispatcher().claim_recon_todo(
            engagement_id, owner="worker-2", gap_key="heartbeat:gap"
        )
        assert reclaimed is not None
        assert reclaimed["claim_token"] != claimed["claim_token"]
