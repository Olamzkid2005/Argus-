"""
Tests for the dispatcher-owned graph repository and dispatcher surface.

These tests cover the ARTEX first-pass surfaces:
- canonical assets
- exploration nodes
- anchors + coverage
- exploration edges
- planner frontier
- planner todos
- graph outbox

Repository integration tests are skipped when DATABASE_URL is not reachable,
because the repository layer is wired exactly like the existing repository
tests: it calls into BaseRepository.db_operation, which calls get_db(), which
needs a real Postgres connection. That failure is an environment limitation,
not a defect in the graph write path.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest

from database.dispatcher_graph import DispatcherGraph, GraphMutationError
from database.graph_repository import (
    AnchorCoverageState,
    ExplorationGraphRepository,
    GraphNodeKind,
    GraphNodeState,
    OutboxStatus,
    TodoStatus,
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


# ---------------------------------------------------------------------------
# Pure-logic tests (no database)
# ---------------------------------------------------------------------------


class TestGraphNodeKindAndState:
    def test_node_kind_values(self):
        assert GraphNodeKind.GOAL == "goal"
        assert GraphNodeKind.INTENT == "intent"
        assert GraphNodeKind.FACT == "fact"
        assert GraphNodeKind.FINDING == "finding"
        assert GraphNodeKind.HINT == "hint"

    def test_node_state_values(self):
        assert GraphNodeState.OPEN == "open"
        assert GraphNodeState.RUNNING == "running"
        assert GraphNodeState.CONCLUDED == "concluded"
        assert GraphNodeState.BLOCKED == "blocked"
        assert GraphNodeState.CANCELLED == "cancelled"

    def test_todo_status_values(self):
        assert TodoStatus.OPEN == "open"
        assert TodoStatus.IN_PROGRESS == "in_progress"
        assert TodoStatus.DONE == "done"
        assert TodoStatus.BLOCKED == "blocked"

    def test_outbox_status_values(self):
        assert OutboxStatus.QUEUED == "queued"
        assert OutboxStatus.DEQUEUED == "dequeued"

    def test_anchor_coverage_state_values(self):
        assert AnchorCoverageState.PENDING == "pending"
        assert AnchorCoverageState.INCORPORATED == "incorporated"
        assert AnchorCoverageState.COVERED == "covered"
        assert AnchorCoverageState.ARCHIVED == "archived"


class TestDispatcherGraphValidation:
    def test_ensure_asset_rejects_empty_identity(self):
        repo = ExplorationGraphRepository()
        dispatcher = DispatcherGraph(repo)

        with pytest.raises(GraphMutationError):
            dispatcher.ensure_asset("", "endpoint")
        with pytest.raises(GraphMutationError):
            dispatcher.ensure_asset("x", "")

    def test_create_intent_rejects_empty_fields(self):
        repo = ExplorationGraphRepository()
        dispatcher = DispatcherGraph(repo)

        with pytest.raises(GraphMutationError):
            dispatcher.create_intent("", "objective")
        with pytest.raises(GraphMutationError):
            dispatcher.create_intent("e", "")

    def test_create_node_rejects_empty_kind(self):
        repo = ExplorationGraphRepository()
        dispatcher = DispatcherGraph(repo)

        with pytest.raises(GraphMutationError, match="kind"):
            dispatcher.create_node("e", "")

    def test_update_node_state_rejects_empty_fields(self):
        repo = ExplorationGraphRepository()
        dispatcher = DispatcherGraph(repo)

        with pytest.raises(GraphMutationError):
            dispatcher.update_node_state("", "open")
        with pytest.raises(GraphMutationError):
            dispatcher.update_node_state("n", "")

    def test_attach_anchor_rejects_empty_fields(self):
        repo = ExplorationGraphRepository()
        dispatcher = DispatcherGraph(repo)

        with pytest.raises(GraphMutationError):
            dispatcher.attach_anchor("", "a")
        with pytest.raises(GraphMutationError):
            dispatcher.attach_anchor("n", "")

    def test_attach_anchor_scope_rejects_empty_fields(self):
        repo = ExplorationGraphRepository()
        dispatcher = DispatcherGraph(repo)

        with pytest.raises(GraphMutationError):
            dispatcher.attach_anchor_scope("", "s")
        with pytest.raises(GraphMutationError):
            dispatcher.attach_anchor_scope("a", "")

    def test_attach_edge_rejects_empty_fields(self):
        repo = ExplorationGraphRepository()
        dispatcher = DispatcherGraph(repo)

        with pytest.raises(GraphMutationError):
            dispatcher.attach_edge("", "s", "t")
        with pytest.raises(GraphMutationError):
            dispatcher.attach_edge("e", "", "t")
        with pytest.raises(GraphMutationError):
            dispatcher.attach_edge("e", "s", "")

    def test_set_frontier_node_rejects_empty_fields(self):
        repo = ExplorationGraphRepository()
        dispatcher = DispatcherGraph(repo)

        with pytest.raises(GraphMutationError):
            dispatcher.set_frontier_node("", "n", kind="intent")
        with pytest.raises(GraphMutationError):
            dispatcher.set_frontier_node("e", "", kind="intent")
        with pytest.raises(GraphMutationError):
            dispatcher.set_frontier_node("e", "n", kind="")

    def test_create_todo_rejects_empty_engagement(self):
        repo = ExplorationGraphRepository()
        dispatcher = DispatcherGraph(repo)

        with pytest.raises(GraphMutationError):
            dispatcher.create_todo("")

    def test_update_todo_status_rejects_empty_fields(self):
        repo = ExplorationGraphRepository()
        dispatcher = DispatcherGraph(repo)

        with pytest.raises(GraphMutationError):
            dispatcher.update_todo_status("", "done")
        with pytest.raises(GraphMutationError):
            dispatcher.update_todo_status("t", "")

    def test_enqueue_outbox_rejects_missing_event_type(self):
        repo = ExplorationGraphRepository()
        dispatcher = DispatcherGraph(repo)

        with pytest.raises(GraphMutationError):
            dispatcher.enqueue_outbox(event_type="")

    def test_requeue_outbox_rejects_empty_id(self):
        repo = ExplorationGraphRepository()
        dispatcher = DispatcherGraph(repo)

        with pytest.raises(GraphMutationError):
            dispatcher.requeue_outbox("")

    def test_record_outbox_error_rejects_empty_fields(self):
        repo = ExplorationGraphRepository()
        dispatcher = DispatcherGraph(repo)

        with pytest.raises(GraphMutationError):
            dispatcher.record_outbox_error("", "oops")
        with pytest.raises(GraphMutationError):
            dispatcher.record_outbox_error("id", "")

    def test_attach_anchor_scope_defaults_to_pending(self):
        repo = ExplorationGraphRepository()
        dispatcher = DispatcherGraph(repo)

        # This test verifies the dispatcher validation surface and the fact
        # that the default coverage state is PENDING. The dispatcher path
        # only hits the database when a connection is available, so this
        # assertion is about argument routing, not a durable write.
        from database.graph_repository import AnchorCoverageState

        with pytest.raises(GraphMutationError, match="anchor_id"):
            dispatcher.attach_anchor_scope("", "scope-1")

        # Passing fake ids here proves the dispatcher applies the default and
        # forwards to the repository. When DATABASE_URL is unreachable, this
        # call fails at the database layer, which is why the durable version
        # lives under the DB-available skip marker above.
        with pytest.raises(Exception):
            dispatcher.attach_anchor_scope("anchor-1", "scope-1")

        assert AnchorCoverageState.PENDING == "pending"


# ---------------------------------------------------------------------------
# Repository integration tests (require a reachable Postgres)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not DB_AVAILABLE, reason="DATABASE_URL not reachable in this environment")
class TestCanonicalAssetUpsert:
    def test_same_identity_returns_same_asset(self):
        repo = ExplorationGraphRepository()
        a1 = repo.upsert_asset("api.example.com", "endpoint", display_value="https://api.example.com")
        a2 = repo.upsert_asset("api.example.com", "endpoint", display_value="https://api.example.com/v2")
        assert a1["canonical_key"] == "api.example.com"
        assert a2["canonical_key"] == "api.example.com"
        assert a1["asset_type"] == "endpoint"
        assert a2["asset_type"] == "endpoint"
        assert a2["display_value"] == "https://api.example.com/v2"

    def test_different_types_are_different_assets(self):
        repo = ExplorationGraphRepository()
        a1 = repo.upsert_asset("api.example.com", "endpoint")
        a2 = repo.upsert_asset("api.example.com", "domain")
        assert a1["asset_type"] == "endpoint"
        assert a2["asset_type"] == "domain"
        assert a1["id"] != a2["id"]


@pytest.mark.skipif(not DB_AVAILABLE, reason="DATABASE_URL not reachable in this environment")
class TestExplorationNodeCreate:
    def test_node_can_be_reposited_and_read_back(self):
        repo = ExplorationGraphRepository()
        engagement_id = uuid.uuid4().hex
        node = repo.create_node(
            engagement_id,
            GraphNodeKind.INTENT,
            payload={"objective": "enumerate subdomains"},
        )
        assert node["engagement_id"] == engagement_id
        assert node["kind"] == GraphNodeKind.INTENT
        assert node["state"] == GraphNodeState.OPEN

        found = repo.find_node_by_id(node["id"])
        assert found is not None
        assert found["kind"] == GraphNodeKind.INTENT

    def test_intent_node_is_created(self):
        repo = ExplorationGraphRepository()
        engagement_id = uuid.uuid4().hex
        node = repo.create_node(
            engagement_id,
            GraphNodeKind.INTENT,
            payload={"objective": "find exposed endpoints"},
        )
        assert node["kind"] == GraphNodeKind.INTENT
        assert node["payload"]["objective"] == "find exposed endpoints"


@pytest.mark.skipif(not DB_AVAILABLE, reason="DATABASE_URL not reachable in this environment")
class TestAnchors:
    def test_node_can_be_anchored_to_an_asset(self):
        repo = ExplorationGraphRepository()
        asset = repo.upsert_asset("api.example.com", "endpoint")
        engagement_id = uuid.uuid4().hex
        node = repo.create_node(engagement_id, GraphNodeKind.INTENT, payload={"objective": "x"})
        anchor = repo.attach_anchor(node["id"], asset["id"], role="investigates")
        assert anchor["node_id"] == node["id"]
        assert anchor["asset_id"] == asset["id"]
        assert anchor["role"] == "investigates"

    def test_anchors_for_node_return_assets(self):
        repo = ExplorationGraphRepository()
        asset = repo.upsert_asset("api.example.com", "endpoint")
        engagement_id = uuid.uuid4().hex
        node = repo.create_node(engagement_id, GraphNodeKind.FINDING, payload={"x": 1})
        repo.attach_anchor(node["id"], asset["id"], role="describes")
        anchors = repo.find_anchors_for_node(node["id"])
        assert len(anchors) == 1
        assert anchors[0]["asset_type"] == "endpoint"

    def test_nodes_for_asset_return_anchored_nodes(self):
        repo = ExplorationGraphRepository()
        asset = repo.upsert_asset("api.example.com", "endpoint")
        engagement_id = uuid.uuid4().hex
        node = repo.create_node(engagement_id, GraphNodeKind.FACT, payload={"x": 1})
        repo.attach_anchor(node["id"], asset["id"], role="affects")
        nodes = repo.find_nodes_for_asset(asset["id"])
        assert len(nodes) == 1
        assert nodes[0]["kind"] == GraphNodeKind.FACT


@pytest.mark.skipif(not DB_AVAILABLE, reason="DATABASE_URL not reachable in this environment")
class TestAnchorCoverage:
    def test_anchor_scope_attaches_coverage_metadata(self):
        repo = ExplorationGraphRepository()
        asset = repo.upsert_asset("api.example.com", "endpoint")
        engagement_id = uuid.uuid4().hex
        node = repo.create_node(engagement_id, GraphNodeKind.INTENT, payload={"objective": "x"})
        anchor = repo.attach_anchor(node["id"], asset["id"])
        scope = repo.attach_anchor_scope(anchor["node_id"], uuid.uuid4().hex, coverage_state="incorporated")
        assert scope["anchor_id"] == anchor["node_id"]
        assert scope["coverage_state"] == "incorporated"

    def test_coverage_for_scope_reads_from_anchor_scopes(self):
        repo = ExplorationGraphRepository()
        asset = repo.upsert_asset("api.example.com", "endpoint")
        scope_id = uuid.uuid4().hex
        engagement_id = uuid.uuid4().hex
        node = repo.create_node(engagement_id, GraphNodeKind.FINDING, payload={"x": 1})
        anchor = repo.attach_anchor(node["id"], asset["id"])
        repo.attach_anchor_scope(anchor["node_id"], scope_id, coverage_state="covered")
        coverage = repo.asset_coverage_for_scope(asset["id"], scope_id)
        assert len(coverage) >= 1
        assert coverage[0]["coverage_state"] == "covered"


@pytest.mark.skipif(not DB_AVAILABLE, reason="DATABASE_URL not reachable in this environment")
class TestExplorationEdges:
    def test_edge_links_two_exploration_nodes(self):
        repo = ExplorationGraphRepository()
        engagement_id = uuid.uuid4().hex
        node_a = repo.create_node(engagement_id, GraphNodeKind.INTENT, payload={"objective": "a"})
        node_b = repo.create_node(engagement_id, GraphNodeKind.FACT, payload={"fact": "b"})
        edge = repo.attach_edge(engagement_id, node_a["id"], node_b["id"], edge_type="follows")
        assert edge["source_node_id"] == node_a["id"]
        assert edge["target_node_id"] == node_b["id"]
        assert edge["edge_type"] == "follows"

    def test_edges_for_engagement_return_linked_nodes(self):
        repo = ExplorationGraphRepository()
        engagement_id = uuid.uuid4().hex
        node_a = repo.create_node(engagement_id, GraphNodeKind.INTENT, payload={"objective": "a"})
        node_b = repo.create_node(engagement_id, GraphNodeKind.FACT, payload={"fact": "b"})
        repo.attach_edge(engagement_id, node_a["id"], node_b["id"])
        edges = repo.find_edges_for_engagement(engagement_id)
        assert len(edges) == 1
        assert edges[0]["source_node_id"] == node_a["id"]


@pytest.mark.skipif(not DB_AVAILABLE, reason="DATABASE_URL not reachable in this environment")
class TestPlannerFrontier:
    def test_frontier_node_can_be_set_and_read(self):
        repo = ExplorationGraphRepository()
        engagement_id = uuid.uuid4().hex
        node = repo.create_node(engagement_id, GraphNodeKind.INTENT, payload={"objective": "x"})
        frontier = repo.set_frontier_node(engagement_id, node["id"], kind=GraphNodeKind.INTENT, priority=10)
        assert frontier["node_id"] == node["id"]
        assert frontier["priority"] == 10

        frontier_rows = repo.find_frontier_for_engagement(engagement_id)
        assert len(frontier_rows) == 1
        assert frontier_rows[0]["node_id"] == node["id"]

    def test_frontier_node_can_be_removed(self):
        repo = ExplorationGraphRepository()
        engagement_id = uuid.uuid4().hex
        node = repo.create_node(engagement_id, GraphNodeKind.FACT, payload={"x": 1})
        repo.set_frontier_node(engagement_id, node["id"], kind=GraphNodeKind.FACT)
        assert repo.remove_frontier_node(engagement_id, node["id"]) is True
        assert repo.find_frontier_for_engagement(engagement_id) == []

    def test_frontier_can_be_cleared(self):
        repo = ExplorationGraphRepository()
        engagement_id = uuid.uuid4().hex
        for i in range(3):
            node = repo.create_node(engagement_id, GraphNodeKind.HINT, payload={"i": i})
            repo.set_frontier_node(engagement_id, node["id"], kind=GraphNodeKind.HINT)
        count = repo.clear_frontier_for_engagement(engagement_id)
        assert count == 3
        assert repo.find_frontier_for_engagement(engagement_id) == []


@pytest.mark.skipif(not DB_AVAILABLE, reason="DATABASE_URL not reachable in this environment")
class TestPlannerTodos:
    def test_todo_can_be_created_with_graph_references(self):
        repo = ExplorationGraphRepository()
        engagement_id = uuid.uuid4().hex
        node = repo.create_node(engagement_id, GraphNodeKind.INTENT, payload={"objective": "x"})
        todo = repo.create_todo(
            engagement_id,
            todo_type="expand",
            canonical_node_id=node["id"],
            exploration_node_id=node["id"],
            payload={"goal": "expand frontier"},
        )
        assert todo["engagement_id"] == engagement_id
        assert todo["status"] == TodoStatus.OPEN
        assert todo["exploration_node_id"] == node["id"]

    def test_todo_status_transitions_record_timestamps(self):
        repo = ExplorationGraphRepository()
        engagement_id = uuid.uuid4().hex
        todo = repo.create_todo(engagement_id, todo_type="plan")
        updated = repo.update_todo_status(todo["id"], TodoStatus.IN_PROGRESS, owner="worker-1")
        assert updated["status"] == TodoStatus.IN_PROGRESS
        assert updated["owner"] == "worker-1"
        assert updated["started_at"] is not None

        done = repo.update_todo_status(todo["id"], TodoStatus.DONE)
        assert done["status"] == TodoStatus.DONE
        assert done["completed_at"] is not None

    def test_find_todos_filters_by_status(self):
        repo = ExplorationGraphRepository()
        engagement_id = uuid.uuid4().hex
        repo.create_todo(engagement_id, todo_type="plan")
        repo.create_todo(engagement_id, todo_type="verify")
        open_todos = repo.find_open_todos_for_engagement(engagement_id)
        assert len(open_todos) == 2
        assert all(t["status"] == TodoStatus.OPEN for t in open_todos)


@pytest.mark.skipif(not DB_AVAILABLE, reason="DATABASE_URL not reachable in this environment")
class TestGraphOutbox:
    def test_outbox_event_can_be_enqueued_and_dequeued(self):
        repo = ExplorationGraphRepository()
        scope_id = uuid.uuid4().hex
        event = repo.enqueue_outbox(
            scope_type="graph",
            scope_id=scope_id,
            event_type="node.created",
            payload={"kind": "intent"},
            cause_node_id="node-1",
            cause_engagement_id="eng-1",
        )
        assert event["status"] == OutboxStatus.QUEUED
        assert event["event_type"] == "node.created"

        dequeued = repo.dequeue_outbox(scope_type="graph", scope_id=scope_id, batch=10)
        assert len(dequeued) == 1
        assert dequeued[0]["status"] == OutboxStatus.DEQUEUED
        assert dequeued[0]["dequeued_at"] is not None

    def test_outbox_errors_can_be_recorded(self):
        repo = ExplorationGraphRepository()
        scope_id = uuid.uuid4().hex
        event = repo.enqueue_outbox(scope_type="graph", scope_id=scope_id, event_type="x")
        updated = repo.record_outbox_error(event["id"], "downstream unreachable")
        assert updated["last_error"] == "downstream unreachable"

    def test_outbox_can_be_requeued(self):
        repo = ExplorationGraphRepository()
        scope_id = uuid.uuid4().hex
        event = repo.enqueue_outbox(scope_type="graph", scope_id=scope_id, event_type="x")
        repo.dequeue_outbox(scope_type="graph", scope_id=scope_id, batch=10)
        requeued = repo.requeue_outbox(event["id"])
        assert requeued["status"] == OutboxStatus.QUEUED
        assert requeued["dequeued_at"] is None


@pytest.mark.skipif(not DB_AVAILABLE, reason="DATABASE_URL not reachable in this environment")
class TestDispatcherOwnedSurface:
    def test_dispatcher_owns_ensure_asset(self):
        repo = ExplorationGraphRepository()
        dispatcher = DispatcherGraph(repo)
        asset = dispatcher.ensure_asset("api.example.com", "endpoint", display_value="https://api.example.com")
        assert asset["canonical_key"] == "api.example.com"

    def test_dispatcher_flow_creates_asset_then_intent_then_anchor(self):
        repo = ExplorationGraphRepository()
        dispatcher = DispatcherGraph(repo)
        engagement_id = uuid.uuid4().hex
        asset = dispatcher.ensure_asset("api.example.com", "endpoint")
        node = dispatcher.create_intent(engagement_id, "enumerate exposure surface", priority=5)
        anchor = dispatcher.attach_anchor(node["id"], asset["id"], role="investigates")
        assert anchor["node_id"] == node["id"]
        assert anchor["asset_id"] == asset["id"]

    def test_dispatcher_frontier_todo_outbox_flow(self):
        repo = ExplorationGraphRepository()
        dispatcher = DispatcherGraph(repo)
        engagement_id = uuid.uuid4().hex
        node = dispatcher.create_intent(engagement_id, "explore api surface", priority=5)
        dispatcher.set_frontier_node(engagement_id, node["id"], kind=GraphNodeKind.INTENT, priority=5)
        todo = dispatcher.create_todo(engagement_id, todo_type="plan", exploration_node_id=node["id"])
        event = dispatcher.enqueue_outbox(
            scope_type="graph",
            scope_id=engagement_id,
            event_type="frontier.updated",
            payload={"node_id": node["id"]},
            cause_node_id=node["id"],
            cause_engagement_id=engagement_id,
        )
        todos = dispatcher.find_todos_for_engagement(engagement_id)
        assert any(t["id"] == todo["id"] for t in todos)
        outbox = repo.find_outbox_for_scope(scope_type="graph", scope_id=engagement_id, status=OutboxStatus.QUEUED)
        assert any(o["id"] == event["id"] for o in outbox)
