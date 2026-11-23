"""
Argus graph repository — canonical asset graph + exploration graph + anchors + coverage + planner frontier + todos + outbox.

This is the dispatcher-owned persistence contract for the first exploration
implementation pass. Workers/agents should not commit graph state directly;
mutations are submitted through dispatcher-owned surfaces that use this
repository under the dispatcher's transaction/ownership rules.
"""

from __future__ import annotations

from typing import Any

from psycopg2.extras import Json, RealDictCursor

from database.graph_identity import ASSET_TYPES, asset_in_scope
from database.graph_ownership import require_graph_write_owner
from database.repositories.base import BaseRepository


class GraphMutationError(Exception):
    """Dispatched graph mutation was invalid or rejected."""


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


class AnchorCoverageState(str):
    PENDING = "pending"
    INCORPORATED = "incorporated"
    COVERED = "covered"
    ARCHIVED = "archived"


class TodoStatus(str):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"


class OutboxStatus(str):
    QUEUED = "queued"
    DEQUEUED = "dequeued"


class ExplorationGraphRepository(BaseRepository):
    """
    Canonical exploration graph persistence.

    Responsibilities for the first implementation pass:
      - canonical asset upsert by identity
      - exploration node create/read by id/engagement
      - explicit anchors between nodes and assets
      - anchor scopes and coverage metadata
      - per-engagement exploration edges
      - planner frontier rows
      - planner todos
      - graph outbox

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
        parent_asset_id: str | None = None,
        parent_relationship: str | None = None,
    ) -> dict[str, Any]:
        """
        Insert or update a canonical asset by identity.

        Identity is (scope, canonical_key, asset_type): the same asset discovered
        under two different scopes stays two rows (A-03), while unscoped assets
        share one bucket. Returns the current asset row.
        """
        require_graph_write_owner("upsert_asset")
        if metadata is None:
            metadata = {}

        with self.db_operation(
            commit=True, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                INSERT INTO graph_assets
                    (scope_id, canonical_key, asset_type, display_value, metadata,
                     last_seen_at, parent_asset_id, parent_relationship)
                VALUES (%s, %s, %s, %s, %s, NOW(), %s, %s)
                ON CONFLICT (
                    COALESCE(scope_id, '00000000-0000-0000-0000-000000000000'::uuid),
                    canonical_key,
                    asset_type
                ) DO UPDATE SET
                    display_value = COALESCE(EXCLUDED.display_value, graph_assets.display_value),
                    metadata = EXCLUDED.metadata,
                    parent_asset_id = COALESCE(EXCLUDED.parent_asset_id, graph_assets.parent_asset_id),
                    parent_relationship = COALESCE(EXCLUDED.parent_relationship, graph_assets.parent_relationship),
                    last_seen_at = NOW(),
                    updated_at = NOW()
                RETURNING *
                """,
                (
                    scope_id,
                    canonical_key,
                    asset_type,
                    display_value,
                    Json(metadata),
                    parent_asset_id,
                    parent_relationship,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("graph_assets upsert did not return a row")
            return dict(row)

    def find_asset_by_identity(
        self,
        canonical_key: str,
        asset_type: str,
        *,
        scope_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Return one canonical asset by its identity, if it exists."""
        with self.db_operation(
            commit=False, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                SELECT * FROM graph_assets
                WHERE canonical_key = %s AND asset_type = %s
                  AND scope_id IS NOT DISTINCT FROM %s
                """,
                (canonical_key, asset_type, scope_id),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def find_assets_for_scope(
        self,
        scope_id: str,
        *,
        asset_type: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """
        List canonical assets owned by one scope.

        Strictly scoped: assets belonging to another scope are never returned, so
        two tenants cannot see each other's graph (A-03).
        """
        if not scope_id:
            raise GraphMutationError("scope_id is required")
        with self.db_operation(
            commit=False, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            clauses = ["scope_id = %s"]
            values: list[Any] = [scope_id]
            if asset_type is not None:
                clauses.append("asset_type = %s")
                values.append(asset_type)
            cursor.execute(
                f"SELECT * FROM graph_assets WHERE {' AND '.join(clauses)} "
                "ORDER BY asset_type, canonical_key LIMIT %s",
                values + [limit],
            )
            return [dict(row) for row in cursor.fetchall()]

    def record_asset_observation(
        self,
        *,
        asset_id: str | None,
        asset_type: str,
        observed_value: str,
        source: str,
        scope_id: str | None = None,
        parser_version: str | None = None,
        confidence: float | None = None,
        accepted: bool = True,
        rejection_reason: str | None = None,
    ) -> dict[str, Any]:
        """
        Record a raw asset observation, merging replays onto one row (A-16).

        Rejected observations keep asset_id NULL: they are retained for audit but
        never become schedulable assets.
        """
        require_graph_write_owner("record_asset_observation")
        if accepted and asset_id is None:
            raise GraphMutationError("an accepted observation requires asset_id")
        if not accepted and not rejection_reason:
            raise GraphMutationError("a rejected observation requires a reason")

        with self.db_operation(
            commit=True, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                INSERT INTO graph_asset_observations
                    (asset_id, scope_id, asset_type, observed_value, source,
                     parser_version, confidence, accepted, rejection_reason)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (
                    COALESCE(scope_id, '00000000-0000-0000-0000-000000000000'::uuid),
                    asset_type,
                    observed_value,
                    source
                ) DO UPDATE SET
                    asset_id = COALESCE(EXCLUDED.asset_id, graph_asset_observations.asset_id),
                    accepted = EXCLUDED.accepted OR graph_asset_observations.accepted,
                    rejection_reason = CASE
                        WHEN EXCLUDED.accepted THEN NULL
                        ELSE COALESCE(EXCLUDED.rejection_reason, graph_asset_observations.rejection_reason)
                    END,
                    parser_version = COALESCE(EXCLUDED.parser_version, graph_asset_observations.parser_version),
                    confidence = COALESCE(EXCLUDED.confidence, graph_asset_observations.confidence),
                    observation_count = graph_asset_observations.observation_count + 1,
                    last_observed_at = NOW(),
                    updated_at = NOW()
                RETURNING *
                """,
                (
                    asset_id,
                    scope_id,
                    asset_type,
                    observed_value,
                    source,
                    parser_version,
                    confidence,
                    accepted,
                    rejection_reason,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("graph_asset_observations write did not return a row")
            return dict(row)

    def find_observations_for_asset(
        self,
        asset_id: str,
        *,
        accepted: bool | None = None,
    ) -> list[dict[str, Any]]:
        """Return the raw observations merged onto one canonical asset."""
        with self.db_operation(
            commit=False, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            clauses = ["asset_id = %s"]
            values: list[Any] = [asset_id]
            if accepted is not None:
                clauses.append("accepted = %s")
                values.append(accepted)
            cursor.execute(
                f"SELECT * FROM graph_asset_observations WHERE {' AND '.join(clauses)} "
                "ORDER BY last_observed_at DESC",
                values,
            )
            return [dict(row) for row in cursor.fetchall()]

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
        require_graph_write_owner("create_node")
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
                    Json(payload),
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

            query = (
                """
                SELECT * FROM graph_nodes
                WHERE """
                + " AND ".join(clauses)
                + """
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """
            )
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
        require_graph_write_owner("attach_anchor")
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
        require_graph_write_owner("update_node_state")
        return self.update_by_id(node_id, {"state": state})

    # --- anchors + coverage ---

    def attach_anchor_scope(
        self,
        anchor_id: str,
        scope_id: str,
        *,
        incorporated_by: str | None = None,
        coverage_state: str | None = None,
    ) -> dict[str, Any]:
        """
        Attach an engagement-scoped anchor handle + coverage metadata on top of a canonical anchor.

        Returns the anchor scope row.
        """
        require_graph_write_owner("attach_anchor_scope")
        if coverage_state is None:
            coverage_state = AnchorCoverageState.PENDING

        with self.db_operation(
            commit=True, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                INSERT INTO graph_anchor_scopes
                    (anchor_id, scope_id, incorporated_by, coverage_state, incorporated_at)
                VALUES (
                    %s, %s, %s, %s,
                    CASE WHEN %s = 'pending' THEN NULL ELSE NOW() END
                )
                ON CONFLICT (anchor_id, scope_id) DO UPDATE SET
                    incorporated_by = COALESCE(EXCLUDED.incorporated_by, graph_anchor_scopes.incorporated_by),
                    -- Re-attaching with the default 'pending' must not regress
                    -- coverage an engagement already established.
                    coverage_state = CASE
                        WHEN EXCLUDED.coverage_state = 'pending'
                        THEN graph_anchor_scopes.coverage_state
                        ELSE EXCLUDED.coverage_state
                    END,
                    incorporated_at = COALESCE(
                        graph_anchor_scopes.incorporated_at,
                        EXCLUDED.incorporated_at
                    ),
                    updated_at = NOW()
                RETURNING *
                """,
                (
                    anchor_id,
                    scope_id,
                    incorporated_by,
                    coverage_state,
                    coverage_state,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("graph_anchor_scopes upsert did not return a row")
            return dict(row)

    def update_anchor_coverage(
        self,
        anchor_id: str,
        scope_id: str,
        *,
        coverage_state: str,
        incorporated_by: str | None = None,
    ) -> dict[str, Any] | None:
        """Update an anchor scope's coverage state."""
        require_graph_write_owner("update_anchor_coverage")
        set_clause = ["coverage_state = %s", "updated_at = NOW()"]
        values: list[Any] = [coverage_state]
        if coverage_state != AnchorCoverageState.PENDING:
            # First time an engagement actually incorporates/records coverage,
            # stamp it; never overwrite the original incorporation time.
            set_clause.append(
                "incorporated_at = COALESCE(graph_anchor_scopes.incorporated_at, NOW())"
            )
        if incorporated_by is not None:
            set_clause.append("incorporated_by = %s")
            values.append(incorporated_by)
        values.append(scope_id)
        values.append(anchor_id)

        with self.db_operation(commit=True, cursor_factory=RealDictCursor) as (conn, cursor):
            cursor.execute(
                f"UPDATE graph_anchor_scopes SET {', '.join(set_clause)} WHERE anchor_id = %s AND scope_id = %s RETURNING *",
                values,
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def find_anchor_scopes_for_anchor(
        self, anchor_id: str, *, scope_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Return anchor scopes for a canonical anchor, optionally filtered by scope."""
        with self.db_operation(
            commit=False, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            clauses = ["anchor_id = %s"]
            values: list[Any] = [anchor_id]
            if scope_id is not None:
                clauses.append("scope_id = %s")
                values.append(scope_id)
            cursor.execute(
                f"SELECT * FROM graph_anchor_scopes WHERE {' AND '.join(clauses)} ORDER BY created_at DESC",
                values,
            )
            return [dict(row) for row in cursor.fetchall()]

    def asset_coverage_for_scope(
        self,
        asset_id: str,
        scope_id: str,
        *,
        authorized_scope: dict | str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Return canonical asset coverage from the perspective of one engagement scope.

        Each row reports the scope's anchor coverage and, when ``authorized_scope``
        is supplied, whether the asset itself is inside the approved scope
        (``in_scope``) and still uncovered (``untested``).
        """
        with self.db_operation(
            commit=False, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                SELECT a.id, a.canonical_key, a.asset_type, a.display_value,
                       a.scope_id, a.parent_asset_id,
                       s.coverage_state, s.incorporated_by, s.incorporated_at,
                       BOOL_OR(s.coverage_state IN ('incorporated', 'covered'))
                           OVER (PARTITION BY a.id) AS covered
                FROM graph_assets AS a
                JOIN graph_anchors AS ga ON ga.asset_id = a.id
                LEFT JOIN graph_anchor_scopes AS s
                    ON s.anchor_id = ga.id AND s.scope_id = %s
                WHERE a.id = %s
                -- Anchors from other scopes left-join to NULL coverage. Put the
                -- requested scope's rows first so callers reading row 0 see the
                -- scope's real coverage state rather than an unrelated NULL.
                ORDER BY s.created_at DESC NULLS LAST
                """,
                (scope_id, asset_id),
            )
            rows = [dict(row) for row in cursor.fetchall()]

        for row in rows:
            covered = bool(row.get("covered"))
            in_scope = (
                asset_in_scope(row["asset_type"], row["canonical_key"], authorized_scope)
                if authorized_scope is not None
                else True
            )
            row["covered"] = covered
            row["in_scope"] = in_scope
            row["untested"] = in_scope and not covered
        return rows

    def compute_scope_coverage(
        self,
        scope_id: str,
        *,
        authorized_scope: dict | str | None = None,
    ) -> dict[str, Any]:
        """
        Compute discovered-asset coverage for one scope (A2).

        Unlike :meth:`asset_coverage_for_scope` this does not start from anchors:
        every asset discovered for the scope is counted, then classified as
        covered (an anchor in this scope reached incorporated/covered) or untested.
        With ``authorized_scope`` supplied, assets outside the approved scope are
        reported separately instead of being counted as work.
        """
        if not scope_id:
            raise GraphMutationError("scope_id is required")
        with self.db_operation(
            commit=False, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                SELECT a.id, a.canonical_key, a.asset_type, a.display_value,
                       a.scope_id, a.parent_asset_id,
                       COALESCE(
                           BOOL_OR(s.coverage_state IN ('incorporated', 'covered')),
                           FALSE
                       ) AS covered,
                       COUNT(DISTINCT ga.id) AS anchor_count,
                       COUNT(DISTINCT s.id) AS scoped_anchor_count
                FROM graph_assets AS a
                LEFT JOIN graph_anchors AS ga ON ga.asset_id = a.id
                LEFT JOIN graph_anchor_scopes AS s
                    ON s.anchor_id = ga.id AND s.scope_id = %s
                WHERE a.scope_id = %s
                GROUP BY a.id
                ORDER BY a.asset_type, a.canonical_key
                """,
                (scope_id, scope_id),
            )
            rows = cursor.fetchall()

        assets: list[dict[str, Any]] = []
        by_asset_type: dict[str, dict[str, int]] = {}
        for row in rows:
            covered = bool(row["covered"])
            in_scope = (
                asset_in_scope(row["asset_type"], row["canonical_key"], authorized_scope)
                if authorized_scope is not None
                else True
            )
            untested = in_scope and not covered
            entry = {
                "id": row["id"],
                "canonical_key": row["canonical_key"],
                "asset_type": row["asset_type"],
                "display_value": row["display_value"],
                "scope_id": row["scope_id"],
                "parent_asset_id": row["parent_asset_id"],
                "covered": covered,
                "in_scope": in_scope,
                "untested": untested,
                "anchor_count": int(row["anchor_count"]),
                "scoped_anchor_count": int(row["scoped_anchor_count"]),
            }
            assets.append(entry)
            bucket = by_asset_type.setdefault(
                entry["asset_type"],
                {"total": 0, "in_scope": 0, "covered": 0, "untested": 0},
            )
            bucket["total"] += 1
            bucket["in_scope"] += int(in_scope)
            bucket["covered"] += int(covered)
            bucket["untested"] += int(untested)

        return {
            "scope_id": scope_id,
            "assets_total": len(assets),
            "assets_in_scope": sum(1 for asset in assets if asset["in_scope"]),
            "assets_out_of_scope": sum(1 for asset in assets if not asset["in_scope"]),
            "assets_covered": sum(1 for asset in assets if asset["covered"]),
            "assets_untested": sum(1 for asset in assets if asset["untested"]),
            "by_asset_type": by_asset_type,
            "untested_asset_types": sorted(
                asset_type
                for asset_type, counts in by_asset_type.items()
                if counts["untested"]
            ),
            "undiscovered_asset_types": sorted(ASSET_TYPES - set(by_asset_type)),
            "assets": assets,
        }

    # --- exploration edges ---

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

        Both endpoints must be exploration nodes of the same engagement; an edge
        that crossed engagements would leak one engagement's graph into another.
        """
        require_graph_write_owner("attach_edge")
        with self.db_operation(
            commit=True, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                SELECT id FROM graph_nodes
                WHERE engagement_id = %s AND id IN (%s, %s)
                """,
                (engagement_id, source_node_id, target_node_id),
            )
            owned = {row["id"] for row in cursor.fetchall()}
            if source_node_id not in owned or target_node_id not in owned:
                raise GraphMutationError(
                    "source_node_id and target_node_id must be nodes of engagement "
                    f"{engagement_id}"
                )
            cursor.execute(
                """
                INSERT INTO graph_node_edges
                    (engagement_id, source_node_id, target_node_id, edge_type)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (source_node_id, target_node_id, edge_type) DO UPDATE SET created_at = NOW()
                RETURNING *
                """,
                (engagement_id, source_node_id, target_node_id, edge_type),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("graph_node_edges attach did not return a row")
            return dict(row)

    def find_edges_for_engagement(
        self,
        engagement_id: str,
        *,
        source_node_id: str | None = None,
        target_node_id: str | None = None,
        edge_type: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """List exploration edges for an engagement with optional filters."""
        with self.db_operation(
            commit=False, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            clauses = ["engagement_id = %s"]
            values: list[Any] = [engagement_id]
            if source_node_id is not None:
                clauses.append("source_node_id = %s")
                values.append(source_node_id)
            if target_node_id is not None:
                clauses.append("target_node_id = %s")
                values.append(target_node_id)
            if edge_type is not None:
                clauses.append("edge_type = %s")
                values.append(edge_type)
            cursor.execute(
                f"SELECT * FROM graph_node_edges WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT %s",
                values + [limit],
            )
            return [dict(row) for row in cursor.fetchall()]

    def find_edges_for_node(self, node_id: str) -> list[dict[str, Any]]:
        """Return exploration edges touching a node (as source or target)."""
        with self.db_operation(
            commit=False, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                SELECT * FROM graph_node_edges
                WHERE source_node_id = %s OR target_node_id = %s
                ORDER BY created_at DESC
                """,
                (node_id, node_id),
            )
            return [dict(row) for row in cursor.fetchall()]

    # --- planner frontier ---

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
        Insert or refresh a node in the recoverable per-engagement frontier.
        """
        require_graph_write_owner("set_frontier_node")
        if state is None:
            state = GraphNodeState.OPEN

        with self.db_operation(
            commit=True, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                INSERT INTO planner_frontier
                    (engagement_id, node_id, kind, state, priority, frontier_reason)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (engagement_id, node_id) DO UPDATE SET
                    kind = EXCLUDED.kind,
                    state = EXCLUDED.state,
                    priority = EXCLUDED.priority,
                    frontier_reason = EXCLUDED.frontier_reason,
                    incorporated_at = NOW()
                RETURNING *
                """,
                (engagement_id, node_id, kind, state, priority, frontier_reason),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("planner_frontier upsert did not return a row")
            return dict(row)

    def remove_frontier_node(self, engagement_id: str, node_id: str) -> bool:
        """Remove a node from the frontier. Returns True if a row was removed."""
        require_graph_write_owner("remove_frontier_node")
        with self.db_operation(commit=True) as (conn, cursor):
            cursor.execute(
                "DELETE FROM planner_frontier WHERE engagement_id = %s AND node_id = %s",
                (engagement_id, node_id),
            )
            return cursor.rowcount > 0

    def find_frontier_for_engagement(
        self,
        engagement_id: str,
        *,
        state: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Return the current planner frontier for an engagement."""
        with self.db_operation(
            commit=False, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            # Both planner_frontier and graph_nodes carry engagement_id/state, so
            # these predicates must be qualified or Postgres rejects the query as
            # ambiguous.
            clauses = ["pf.engagement_id = %s"]
            values: list[Any] = [engagement_id]
            if state is not None:
                clauses.append("pf.state = %s")
                values.append(state)
            cursor.execute(
                f"SELECT pf.*, n.kind AS node_kind, n.state AS node_state FROM planner_frontier pf JOIN graph_nodes n ON n.id = pf.node_id WHERE {' AND '.join(clauses)} ORDER BY pf.priority DESC, pf.incorporated_at ASC LIMIT %s",
                values + [limit],
            )
            return [dict(row) for row in cursor.fetchall()]

    def clear_frontier_for_engagement(self, engagement_id: str) -> int:
        """Clear the frontier for an engagement and return the number of removed rows."""
        require_graph_write_owner("clear_frontier_for_engagement")
        with self.db_operation(commit=True) as (conn, cursor):
            cursor.execute("DELETE FROM planner_frontier WHERE engagement_id = %s", (engagement_id,))
            return cursor.rowcount

    # --- planner todos ---

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
        require_graph_write_owner("create_todo")
        if payload is None:
            payload = {}
        if frontier_position is None:
            frontier_position = {}

        with self.db_operation(
            commit=True, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                INSERT INTO planner_todos
                    (engagement_id, todo_type, canonical_node_id, exploration_node_id,
                     frontier_position, payload, depends_on, owner, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    engagement_id,
                    todo_type,
                    canonical_node_id,
                    exploration_node_id,
                    Json(frontier_position),
                    Json(payload),
                    depends_on,
                    owner,
                    TodoStatus.OPEN,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("planner_todos create did not return a row")
            return dict(row)

    def update_todo_status(
        self,
        todo_id: str,
        status: str,
        *,
        owner: str | None = None,
    ) -> dict[str, Any] | None:
        """Transition a todo status; sets started_at/completed_at as appropriate."""
        require_graph_write_owner("update_todo_status")
        set_parts: list[str] = ["status = %s", "updated_at = NOW()"]
        values: list[Any] = [status]

        if status == TodoStatus.IN_PROGRESS:
            set_parts.append("started_at = NOW()")
        elif status == TodoStatus.DONE:
            set_parts.append("completed_at = NOW()")

        if owner is not None:
            set_parts.append("owner = %s")
            values.append(owner)

        values.append(todo_id)

        with self.db_operation(commit=True, cursor_factory=RealDictCursor) as (conn, cursor):
            cursor.execute(
                f"UPDATE planner_todos SET {', '.join(set_parts)} WHERE id = %s RETURNING *",
                values,
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def find_todos_for_engagement(
        self,
        engagement_id: str,
        *,
        status: str | None = None,
        todo_type: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Return todos for an engagement with optional filters."""
        with self.db_operation(
            commit=False, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            clauses = ["engagement_id = %s"]
            values: list[Any] = [engagement_id]
            if status is not None:
                clauses.append("status = %s")
                values.append(status)
            if todo_type is not None:
                clauses.append("todo_type = %s")
                values.append(todo_type)
            cursor.execute(
                f"SELECT * FROM planner_todos WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT %s",
                values + [limit],
            )
            return [dict(row) for row in cursor.fetchall()]

    def find_open_todos_for_engagement(self, engagement_id: str) -> list[dict[str, Any]]:
        return self.find_todos_for_engagement(
            engagement_id, status=TodoStatus.OPEN
        )

    # --- graph outbox ---

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
        require_graph_write_owner("enqueue_outbox")
        if payload is None:
            payload = {}
        if not scope_id:
            # scope_id is a UUID column; an empty string is not a valid uuid and
            # used to fail deep inside the driver.
            raise GraphMutationError("scope_id is required")

        with self.db_operation(
            commit=True, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                INSERT INTO graph_outbox
                    (scope_type, scope_id, event_type, payload, cause_node_id, cause_engagement_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    scope_type,
                    scope_id,
                    event_type,
                    Json(payload),
                    cause_node_id,
                    cause_engagement_id,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("graph_outbox enqueue did not return a row")
            return dict(row)

    def dequeue_outbox(
        self,
        *,
        scope_id: str,
        scope_type: str = "graph",
        batch: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Claim and return queued outbox rows for a scope.

        This is at-least-once friendly: dequeued rows are marked dequeued and
        timestamped, but they are not deleted, so downstream consumers can
        reconcile against the outbox if needed.
        """
        require_graph_write_owner("dequeue_outbox")
        if not scope_id:
            raise GraphMutationError("scope_id is required")
        with self.db_operation(
            commit=True, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                UPDATE graph_outbox
                SET status = %s, dequeued_at = NOW(), attempts = attempts + 1, updated_at = NOW()
                WHERE id IN (
                    SELECT id FROM graph_outbox
                    WHERE scope_type = %s AND scope_id = %s AND status = %s
                    ORDER BY created_at ASC
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING *
                """,
                (OutboxStatus.DEQUEUED, scope_type, scope_id, OutboxStatus.QUEUED, batch),
            )
            return [dict(row) for row in cursor.fetchall()]

    def find_outbox_for_scope(
        self,
        *,
        scope_id: str,
        scope_type: str = "graph",
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Read outbox rows for a scope without claiming them."""
        if not scope_id:
            raise GraphMutationError("scope_id is required")
        with self.db_operation(
            commit=False, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            clauses = ["scope_type = %s", "scope_id = %s"]
            values: list[Any] = [scope_type, scope_id]
            if status is not None:
                clauses.append("status = %s")
                values.append(status)
            cursor.execute(
                f"SELECT * FROM graph_outbox WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT %s",
                values + [limit],
            )
            return [dict(row) for row in cursor.fetchall()]

    def record_outbox_error(self, outbox_id: str, error: str) -> dict[str, Any] | None:
        """Record a dequeue error on an outbox row."""
        require_graph_write_owner("record_outbox_error")
        with self.db_operation(commit=True, cursor_factory=RealDictCursor) as (conn, cursor):
            cursor.execute(
                "UPDATE graph_outbox SET last_error = %s, updated_at = NOW() WHERE id = %s RETURNING *",
                (error, outbox_id),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def requeue_outbox(self, outbox_id: str) -> dict[str, Any] | None:
        """Put a dequeued/errored outbox row back into the queue."""
        require_graph_write_owner("requeue_outbox")
        with self.db_operation(commit=True, cursor_factory=RealDictCursor) as (conn, cursor):
            cursor.execute(
                "UPDATE graph_outbox SET status = %s, dequeued_at = NULL, updated_at = NOW() WHERE id = %s RETURNING *",
                (OutboxStatus.QUEUED, outbox_id),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
