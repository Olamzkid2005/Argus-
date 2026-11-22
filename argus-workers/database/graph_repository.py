"""
Argus graph repository — canonical asset graph + exploration graph + anchors.

This is the dispatcher-owned persistence contract for the first exploration
implementation pass. Workers/agents should not commit graph state directly;
mutations are submitted through dispatcher-owned surfaces that use this
repository under the dispatcher's transaction/ownership rules.
"""

from __future__ import annotations

from typing import Any

from database.repositories.base import BaseRepository
from psycopg2.extras import RealDictCursor


class GraphAssetState(str):
    pass


class GraphNodeKind(str):
    GOAL = "goal"
    INTENT = "intent"
    FACT = "fact"
    FINDING = "finding"
    HINT = "hint"


class GraphNodeState(str):
    OPEN = "open"
    RUNNING = "running"
    CONCLUDED = "concluded"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class ExplorationGraphRepository(BaseRepository):
    """
    Canonical exploration graph persistence.

    Responsibilities for the first implementation pass:
      - canonical asset upsert by identity
      - exploration node create/read by id/engagement
      - explicit anchors between nodes and assets

    This repository is dispatcher-owned. It does not implement claim/lease/cancellation
    semantics itself; those stay in the dispatcher control plane and use this repo
    under the dispatcher's transaction boundaries.
    """

    table_name = "graph_nodes"
    id_column = "id"

    def upsert_asset(
        self,
        canonical_key: str,
        asset_type: str,
        *,
        display_value: str | None = None,
        scope_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Insert or update a canonical asset by identity.

        Returns the current asset row.
        """
        if metadata is None:
            metadata = {}

        with self.db_operation(
            commit=True, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                INSERT INTO graph_assets AS a
                    (id, scope_id, canonical_key, asset_type, display_value, metadata, last_seen_at)
                VALUES (
                    coalesce((
                        SELECT id FROM graph_assets
                        WHERE canonical_key = %s AND asset_type = %s
                    ), gen_random_uuid()),
                    %s, %s, %s, %s, %s, NOW()
                )
                ON CONFLICT (canonical_key, asset_type) DO UPDATE SET
                    display_value = EXCLUDED.display_value,
                    metadata = EXCLUDED.metadata,
                    last_seen_at = NOW(),
                    updated_at = NOW()
                RETURNING a.*
                """,
                (
                    canonical_key,
                    asset_type,
                    scope_id,
                    canonical_key,
                    asset_type,
                    display_value,
                    metadata,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("graph_assets upsert did not return a row")
            return dict(row)

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
        """
        Create an exploration node for an engagement.

        payload is used together with engagement_id and kind to form the unique
        node identity for the first pass.
        """
        if payload is None:
            payload = {}
        if state is None:
            state = GraphNodeState.OPEN

        with self.db_operation(
            commit=True, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                INSERT INTO graph_nodes
                    (engagement_id, kind, payload, state, priority, origin, owner)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    engagement_id,
                    kind,
                    payload,
                    state,
                    priority,
                    origin,
                    owner,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("graph_nodes create did not return a row")
            return dict(row)

    def find_node_by_id(self, node_id: str) -> dict[str, Any] | None:
        return self.find_by_id(node_id)

    def find_nodes_by_engagement(
        self,
        engagement_id: str,
        *,
        kind: str | None = None,
        state: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        List exploration nodes for an engagement, optionally filtered by kind/state.
        """
        with self.db_operation(
            commit=False, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            clauses: list[str] = ["engagement_id = %s"]
            values: list[Any] = [engagement_id]

            if kind is not None:
                clauses.append("kind = %s")
                values.append(kind)
            if state is not None:
                clauses.append("state = %s")
                values.append(state)

            query = """
                SELECT * FROM graph_nodes
                WHERE """ + " AND ".join(clauses) + """
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """
            values.append(limit)
            values.append(offset)
            cursor.execute(query, values)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def attach_anchor(
        self,
        node_id: str,
        asset_id: str,
        *,
        role: str = "related",
    ) -> dict[str, Any]:
        """
        Attach an explicit anchor from a node to an asset.

        Returns the anchor row.
        """
        with self.db_operation(
            commit=True, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                INSERT INTO graph_anchors (node_id, asset_id, role)
                VALUES (%s, %s, %s)
                ON CONFLICT (node_id, asset_id, role) DO UPDATE SET created_at = NOW()
                RETURNING *
                """,
                (node_id, asset_id, role),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("graph_anchors attach did not return a row")
            return dict(row)

    def find_anchors_for_node(self, node_id: str) -> list[dict[str, Any]]:
        """
        Return the assets a node is anchored to.
        """
        with self.db_operation(
            commit=False, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                SELECT a.* FROM graph_anchors AS ga
                JOIN graph_assets AS a ON a.id = ga.asset_id
                WHERE ga.node_id = %s
                ORDER BY ga.created_at DESC
                """,
                (node_id,),
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def find_nodes_for_asset(self, asset_id: str) -> list[dict[str, Any]]:
        """
        Return the exploration nodes anchored to an asset.
        """
        with self.db_operation(
            commit=False, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                SELECT n.* FROM graph_anchors AS ga
                JOIN graph_nodes AS n ON n.id = ga.node_id
                WHERE ga.asset_id = %s
                ORDER BY n.created_at DESC
                """,
                (asset_id,),
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def update_node_state(self, node_id: str, state: str) -> dict[str, Any] | None:
        return self.update_by_id(node_id, {"state": state})
