"""
Dispatcher-owned graph mutation surface.

This is the smallest control-plane surface needed to own the first durable
graph write for A-04 and the rest of the ARTEX first-pass surfaces. It exists
so workers/agents return structured output and the dispatcher decides what
actually gets committed through the graph repository.

Every mutating method runs inside ``dispatcher_write_scope`` (C-18): the graph
repository rejects mutations outside that scope at runtime, and
``scripts/check_graph_import_boundary.py`` rejects direct imports of the graph
write surface from worker/agent modules.
"""

from __future__ import annotations

import functools
from typing import Any

from database.graph_ingest import GraphIngestor
from database.graph_ownership import dispatcher_write_scope
from database.graph_repository import (
    AnchorCoverageState,
    ExplorationGraphRepository,
    GraphMutationError,
    GraphNodeKind,
    GraphNodeState,
)


def dispatcher_owned(method):
    """Run a dispatcher mutation inside the C-18 graph write-ownership scope."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with dispatcher_write_scope():
            return method(self, *args, **kwargs)

    return wrapper


class DispatcherGraph:
    """
    Dispatcher-owned graph owner for the first ARTEX implementation pass.

    The dispatcher (not workers/agents) is the only caller expected to use this
    directly for durable mutations.
    """

    def __init__(self, repository: ExplorationGraphRepository) -> None:
        self._repo = repository

    @property
    def repository(self) -> ExplorationGraphRepository:
        """The dispatcher-owned repository, for reads and tests."""
        return self._repo

    # ----- canonical assets -----

    @dispatcher_owned
    def ensure_asset(
        self,
        canonical_key: str,
        asset_type: str,
        *,
        display_value: str | None = None,
        scope_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Ensure a canonical asset exists and return it.

        Canonical assets are authoritative. Engagements reference them through
        anchors and coverage, not by copying subgraphs.
        """
        if not canonical_key or not asset_type:
            raise GraphMutationError("canonical_key and asset_type are required")
        return self._repo.upsert_asset(
            canonical_key,
            asset_type,
            display_value=display_value,
            scope_id=scope_id,
            metadata=metadata,
        )

    # ----- exploration nodes -----

    @dispatcher_owned
    def create_intent(
        self,
        engagement_id: str,
        objective: str,
        *,
        priority: int = 0,
        owner: str | None = None,
    ) -> dict[str, Any]:
        """
        Create an exploration intent node for an engagement.

        Returns the created node.
        """
        if not engagement_id or not objective:
            raise GraphMutationError("engagement_id and objective are required")
        return self._repo.create_node(
            engagement_id,
            kind=GraphNodeKind.INTENT,
            payload={"objective": objective},
            state=GraphNodeState.OPEN,
            priority=priority,
            owner=owner,
        )

    @dispatcher_owned
    def create_node(
        self,
        engagement_id: str,
        kind: str,
        *,
        payload: dict[str, Any] | None = None,
        state: str | None = None,
        priority: int = 0,
        owner: str | None = None,
        origin: str | None = None,
    ) -> dict[str, Any]:
        if not engagement_id:
            raise GraphMutationError("engagement_id is required")
        if not kind:
            raise GraphMutationError("kind is required")
        if payload is None:
            payload = {}
        if state is None:
            state = GraphNodeState.OPEN
        return self._repo.create_node(
            engagement_id,
            kind,
            payload=payload,
            state=state,
            priority=priority,
            owner=owner,
            origin=origin,
        )

    @dispatcher_owned
    def update_node_state(self, node_id: str, state: str) -> dict[str, Any] | None:
        if not node_id or not state:
            raise GraphMutationError("node_id and state are required")
        return self._repo.update_node_state(node_id, state)

    # ----- anchors + coverage -----

    @dispatcher_owned
    def attach_anchor(
        self,
        node_id: str,
        asset_id: str,
        *,
        role: str = "related",
    ) -> dict[str, Any]:
        """
        Anchor an exploration node to a canonical asset.

        Returns the anchor row.
        """
        if not node_id or not asset_id:
            raise GraphMutationError("node_id and asset_id are required")
        return self._repo.attach_anchor(node_id, asset_id, role=role)

    @dispatcher_owned
    def attach_anchor_scope(
        self,
        anchor_id: str,
        scope_id: str,
        *,
        incorporated_by: str | None = None,
        coverage_state: str | None = None,
    ) -> dict[str, Any]:
        """
        Attach an engagement-scoped anchor handle + coverage metadata on top of
        a canonical anchor.

        Canonical assets are authoritative; engagements reference them through
        anchors and coverage, not by copying subgraphs.
        """
        if not anchor_id or not scope_id:
            raise GraphMutationError("anchor_id and scope_id are required")
        if coverage_state is None:
            coverage_state = AnchorCoverageState.PENDING
        return self._repo.attach_anchor_scope(
            anchor_id,
            scope_id,
            incorporated_by=incorporated_by,
            coverage_state=coverage_state,
        )

    @dispatcher_owned
    def update_anchor_coverage(
        self,
        anchor_id: str,
        scope_id: str,
        *,
        coverage_state: str,
        incorporated_by: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Update an anchor scope's coverage state through the dispatcher-owned path.
        """
        if not anchor_id or not scope_id or not coverage_state:
            raise GraphMutationError("anchor_id, scope_id and coverage_state are required")
        return self._repo.update_anchor_coverage(
            anchor_id, scope_id, coverage_state=coverage_state, incorporated_by=incorporated_by
        )

    # ----- exploration edges -----

    @dispatcher_owned
    def attach_edge(
        self,
        engagement_id: str,
        source_node_id: str,
        target_node_id: str,
        *,
        edge_type: str = "related",
    ) -> dict[str, Any]:
        """
        Attach a per-engagement exploration edge between two nodes.

        Exploration edges are separate from canonical anchors: they describe how
        an engagement links exploration nodes to each other, traceable back to the
        canonical node(s) they derive from.
        """
        if not engagement_id or not source_node_id or not target_node_id:
            raise GraphMutationError(
                "engagement_id, source_node_id and target_node_id are required"
            )
        return self._repo.attach_edge(
            engagement_id, source_node_id, target_node_id, edge_type=edge_type
        )

    # ----- planner frontier -----

    @dispatcher_owned
    def set_frontier_node(
        self,
        engagement_id: str,
        node_id: str,
        *,
        kind: str,
        state: str | None = None,
        priority: int = 0,
        frontier_reason: str | None = None,
    ) -> dict[str, Any]:
        """
        Insert or refresh a node in the recoverable per-engagement planner frontier.
        """
        if not engagement_id or not node_id or not kind:
            raise GraphMutationError("engagement_id, node_id and kind are required")
        return self._repo.set_frontier_node(
            engagement_id,
            node_id,
            kind=kind,
            state=state,
            priority=priority,
            frontier_reason=frontier_reason,
        )

    @dispatcher_owned
    def remove_frontier_node(self, engagement_id: str, node_id: str) -> bool:
        """
        Remove a node from the frontier in the dispatcher-owned path.
        """
        if not engagement_id or not node_id:
            raise GraphMutationError("engagement_id and node_id are required")
        return self._repo.remove_frontier_node(engagement_id, node_id)

    @dispatcher_owned
    def clear_frontier_for_engagement(self, engagement_id: str) -> int:
        """
        Clear the frontier for an engagement through the dispatcher-owned path.
        """
        if not engagement_id:
            raise GraphMutationError("engagement_id is required")
        return self._repo.clear_frontier_for_engagement(engagement_id)

    # ----- planner todos -----

    @dispatcher_owned
    def create_todo(
        self,
        engagement_id: str,
        *,
        todo_type: str = "plan",
        canonical_node_id: str | None = None,
        exploration_node_id: str | None = None,
        frontier_position: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        depends_on: str | None = None,
        owner: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a persistent planner todo through the dispatcher-owned path.

        Todos are the durable representation of planner work, not ephemeral
        in-process state.
        """
        if not engagement_id:
            raise GraphMutationError("engagement_id is required")
        return self._repo.create_todo(
            engagement_id,
            todo_type=todo_type,
            canonical_node_id=canonical_node_id,
            exploration_node_id=exploration_node_id,
            frontier_position=frontier_position,
            payload=payload,
            depends_on=depends_on,
            owner=owner,
        )

    @dispatcher_owned
    def update_todo_status(
        self,
        todo_id: str,
        status: str,
        *,
        owner: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Transition a todo status through the dispatcher-owned path.
        """
        if not todo_id or not status:
            raise GraphMutationError("todo_id and status are required")
        return self._repo.update_todo_status(todo_id, status, owner=owner)

    def find_todos_for_engagement(
        self,
        engagement_id: str,
        *,
        status: str | None = None,
        todo_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Return planner todos for an engagement through the dispatcher-owned path.
        """
        if not engagement_id:
            raise GraphMutationError("engagement_id is required")
        return self._repo.find_todos_for_engagement(
            engagement_id, status=status, todo_type=todo_type
        )

    # ----- graph outbox -----

    @dispatcher_owned
    def enqueue_outbox(
        self,
        *,
        event_type: str,
        scope_id: str,
        scope_type: str = "graph",
        payload: dict[str, Any] | None = None,
        cause_node_id: str | None = None,
        cause_engagement_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Stage a graph-side change onto the dispatcher-owned outbox.

        Outbox events let downstream planning/exploration/reconciliation react
        to graph changes without tight coupling.
        """
        if not event_type:
            raise GraphMutationError("event_type is required")
        if not scope_id:
            raise GraphMutationError("scope_id is required")
        return self._repo.enqueue_outbox(
            scope_type=scope_type,
            scope_id=scope_id,
            event_type=event_type,
            payload=payload,
            cause_node_id=cause_node_id,
            cause_engagement_id=cause_engagement_id,
        )

    @dispatcher_owned
    def dequeue_outbox(
        self,
        *,
        scope_id: str,
        scope_type: str = "graph",
        batch: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Claim queued outbox rows for a scope through the dispatcher-owned path.

        This is at-least-once friendly: dequeued rows are marked dequeued and
        timestamped, but not deleted, so downstream consumers can reconcile
        against the outbox if needed.
        """
        if not scope_id:
            raise GraphMutationError("scope_id is required")
        return self._repo.dequeue_outbox(
            scope_type=scope_type, scope_id=scope_id, batch=batch
        )

    @dispatcher_owned
    def record_outbox_error(self, outbox_id: str, error: str) -> dict[str, Any] | None:
        """
        Record a dequeue error on an outbox row through the dispatcher-owned path.
        """
        if not outbox_id or not error:
            raise GraphMutationError("outbox_id and error are required")
        return self._repo.record_outbox_error(outbox_id, error)

    @dispatcher_owned
    def requeue_outbox(self, outbox_id: str) -> dict[str, Any] | None:
        """
        Put a dequeued/errored outbox row back into the queue.
        """
        if not outbox_id:
            raise GraphMutationError("outbox_id is required")
        return self._repo.requeue_outbox(outbox_id)

    # ----- asset ingestion + coverage (A2) -----

    @dispatcher_owned
    def ingest_observation(
        self,
        asset_type: str,
        observed_value: str,
        *,
        source: str,
        scope_id: str | None = None,
        parser_version: str | None = None,
        confidence: float | None = None,
        authorized_scope: dict | str | None = None,
        create_parents: bool = True,
    ) -> dict[str, Any]:
        """
        Ingest one raw observation as canonical graph data.

        Canonicalization, authorized-scope enforcement, parent linking and
        observation merging all happen inside this dispatcher-owned call, so a
        tool cannot add assets to the graph by itself.
        """
        return GraphIngestor(self._repo).ingest_observation(
            asset_type,
            observed_value,
            source=source,
            scope_id=scope_id,
            parser_version=parser_version,
            confidence=confidence,
            authorized_scope=authorized_scope,
            create_parents=create_parents,
        )

    def compute_coverage(
        self,
        scope_id: str,
        *,
        authorized_scope: dict | str | None = None,
    ) -> dict[str, Any]:
        """Read discovered-asset coverage and untested asset classes for a scope."""
        if not scope_id:
            raise GraphMutationError("scope_id is required")
        return self._repo.compute_scope_coverage(
            scope_id, authorized_scope=authorized_scope
        )
