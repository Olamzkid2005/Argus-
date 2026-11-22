"""
Dispatcher-owned graph mutation surface.

This is the smallest control-plane surface needed to own the first durable
graph write for A-04. It exists so workers/agents return structured output and
the dispatcher decides what actually gets committed through the graph repository.

Direct imports of database.graph_repository by worker/agent code paths are
still a C-18 concern; this module is the intended owner for the first pass.
"""

from __future__ import annotations

from database.graph_repository import (
    GraphAssetState,
    GraphNodeKind,
    GraphNodeState,
    ExplorationGraphRepository,
)


class GraphMutationError(Exception):
    """Dispatched graph mutation was invalid or rejected."""


class DispatcherGraph:
    """
    Minimal dispatcher-owned graph owner for the first implementation pass.

    The dispatcher (not workers/agents) is the only caller expected to use this
    directly for durable mutations.
    """

    def __init__(self, repository: ExplorationGraphRepository) -> None:
        self._repo = repository

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

        Dispatcher-owned: callers should not treat this as a free-form asset
        creation API outside dispatcher ownership.
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

    def anchor_node_to_asset(
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
