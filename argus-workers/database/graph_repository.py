"""
Argus graph repository — canonical asset graph + exploration graph + anchors + coverage + planner frontier + todos + outbox.

This is the dispatcher-owned persistence contract for the first exploration
implementation pass. Workers/agents should not commit graph state directly;
mutations are submitted through dispatcher-owned surfaces that use this
repository under the dispatcher's transaction/ownership rules.
"""

from __future__ import annotations

import logging
from typing import Any

from psycopg2.extras import Json, RealDictCursor

from database.graph_identity import (
    ASSET_TYPES,
    asset_in_scope,
    undiscovered_scope_entries,
)
from database.graph_intents import IntentProposal, IntentProposalError
from database.graph_ownership import require_graph_write_owner
from database.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


# Re-exported: callers import these from the repository module.
from database.graph_claims import (
    DEFAULT_INTENT_LEASE_SECONDS,
    DEFAULT_TODO_LEASE_SECONDS,
    LEASE_CLEAR_SQL,
    LEASE_GRANT_SQL,
    claim_token_matches,
    claimable_sql,
    live_claim_sql,
    validate_lease_seconds,
)
from database.graph_errors import (  # noqa: F401  (re-export)
    GraphClaimLostError,
    GraphMutationError,
    GraphTenantViolation,
)


def sanitize_untrusted_text(value: str, *, limit: int = 500) -> str:
    """
    Flatten untrusted text into bounded data (A-13/A-14).

    Trace and tool output is never an instruction. Control characters and
    newlines are collapsed so a trace summary cannot smuggle prompt structure,
    and the value is truncated to a bounded size.
    """
    cleaned = "".join(
        " " if (ch.isspace() or ord(ch) < 32) else ch for ch in str(value or "")
    )
    return " ".join(cleaned.split())[:limit]


#: ``evidence.proof_status`` value that means a verifier observed the exploit.
#: Mirrors ``tools.verification.proof_status.ProofStatus`` without importing it:
#: the graph repository only needs the one word it accepts.
_REPRODUCED_PROOF_STATUS = "reproduced"


def _captured_artifact_refs(evidence: dict) -> list[str]:
    """Paths of artifacts a verifier captured, excluding error logs.

    Mirrors the filter ``tools/verification_agent.py`` applies before it hands
    proof references to the promoter: an error log records a failed attempt, not
    a reproduction.
    """
    refs: list[str] = []
    artifacts = evidence.get("artifacts")
    if not isinstance(artifacts, list):
        return refs
    for artifact in artifacts:
        if isinstance(artifact, str):
            if artifact:
                refs.append(artifact)
            continue
        if not isinstance(artifact, dict):
            continue
        if str(artifact.get("type") or "") == "error_log":
            continue
        path = artifact.get("path")
        if path:
            refs.append(str(path))
    return refs


def verifier_provenance_error(evidence: Any) -> str | None:
    """Explain why *evidence* is not verifier proof (``None`` when it is).

    A goal may only be concluded from findings whose evidence records an actual
    verification, in the shapes Argus's verifier pipeline persists:

    - ``proof_status: "reproduced"`` plus at least one ``proof_evidence_refs``
      or ``proof_control_refs`` entry — the same rule
      ``tools/verification/finding_promoter.py`` uses to write CONFIRMED;
    - ``verification: {verified: true, ...}`` from the HTTP verifiers;
    - ``verification_status: "CONFIRMED"`` from the verification agent *and* the
      artifacts it captured (error logs are failed attempts, not proof).

    Everything else is a claim, not proof: the ``findings.status`` column on its
    own, a scanner's self-reported ``verified`` flag, an analyst feedback verdict
    (``findings.verified``) or a reproduction with no captured artifact.
    """
    if not isinstance(evidence, dict) or not evidence:
        return "no verification evidence was recorded"

    captured = _captured_artifact_refs(evidence)

    proof_status = str(evidence.get("proof_status") or "").strip().lower()
    if proof_status:
        if proof_status != _REPRODUCED_PROOF_STATUS:
            return f"proof_status is {proof_status!r}, not 'reproduced'"
        refs = evidence.get("proof_evidence_refs") or []
        control_refs = evidence.get("proof_control_refs") or []
        if not isinstance(refs, list):
            refs = [refs]
        if not isinstance(control_refs, list):
            control_refs = [control_refs]
        if not (refs or control_refs or captured):
            return "proof_status is 'reproduced' but no evidence or control reference was captured"
        return None

    verification_status = str(evidence.get("verification_status") or "").upper()
    if verification_status == "CONFIRMED":
        # The verification agent records CONFIRMED next to the artifacts it
        # captured. The word alone is as self-asserted as the status column.
        if not captured:
            return (
                "verification_status is 'CONFIRMED' but no artifact was captured"
            )
        return None

    verification = evidence.get("verification")
    if isinstance(verification, dict):
        error = verification.get("error")
        if error:
            return f"the verifier reported an error: {sanitize_untrusted_text(error, limit=120)}"
        verified = verification.get("verified")
        if verified is True or str(verified).strip().lower() == "true":
            return None
        return f"verification.verified is {verified!r}"

    return (
        "no verifier provenance (expected evidence.proof_status='reproduced' with "
        "captured refs, evidence.verification.verified=true, or "
        "evidence.verification_status='CONFIRMED')"
    )


_INTENT_LEASE_SECONDS = DEFAULT_INTENT_LEASE_SECONDS


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
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Insert or update a canonical asset by identity.

        Identity is (scope, canonical_key, asset_type): the same asset discovered
        under two different scopes stays two rows (A-03), while unscoped assets
        share one bucket. A write naming a different tenant than the asset's
        existing owner is rejected rather than silently re-owned. Returns the
        current asset row.
        """
        require_graph_write_owner("upsert_asset")
        if metadata is None:
            metadata = {}

        with self.db_operation(
            commit=True, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            if tenant_id is not None:
                cursor.execute(
                    """
                    SELECT tenant_id FROM graph_assets
                    WHERE canonical_key = %s AND asset_type = %s
                      AND scope_id IS NOT DISTINCT FROM %s
                    """,
                    (canonical_key, asset_type, scope_id),
                )
                existing = cursor.fetchone()
                if (
                    existing is not None
                    and existing["tenant_id"] is not None
                    and str(existing["tenant_id"]) != str(tenant_id)
                ):
                    raise GraphTenantViolation(
                        f"asset {asset_type}:{canonical_key} is owned by tenant "
                        f"{existing['tenant_id']}, not {tenant_id}"
                    )

            cursor.execute(
                """
                INSERT INTO graph_assets
                    (scope_id, canonical_key, asset_type, display_value, metadata,
                     last_seen_at, parent_asset_id, parent_relationship, tenant_id)
                VALUES (%s, %s, %s, %s, %s, NOW(), %s, %s, %s)
                ON CONFLICT (
                    COALESCE(scope_id, '00000000-0000-0000-0000-000000000000'::uuid),
                    canonical_key,
                    asset_type
                ) DO UPDATE SET
                    display_value = COALESCE(EXCLUDED.display_value, graph_assets.display_value),
                    metadata = EXCLUDED.metadata,
                    parent_asset_id = COALESCE(EXCLUDED.parent_asset_id, graph_assets.parent_asset_id),
                    parent_relationship = COALESCE(EXCLUDED.parent_relationship, graph_assets.parent_relationship),
                    tenant_id = COALESCE(EXCLUDED.tenant_id, graph_assets.tenant_id),
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
                    tenant_id,
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
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Record a raw asset observation, merging replays onto one row (A-16).

        Rejected observations keep asset_id NULL: they are retained for audit but
        never become schedulable assets. An observation naming a tenant other than
        the asset's owner is rejected.
        """
        require_graph_write_owner("record_asset_observation")
        if accepted and asset_id is None:
            raise GraphMutationError("an accepted observation requires asset_id")
        if not accepted and not rejection_reason:
            raise GraphMutationError("a rejected observation requires a reason")

        with self.db_operation(
            commit=True, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            if asset_id is not None and tenant_id is not None:
                cursor.execute(
                    "SELECT tenant_id FROM graph_assets WHERE id = %s", (asset_id,)
                )
                existing = cursor.fetchone()
                if (
                    existing is not None
                    and existing["tenant_id"] is not None
                    and str(existing["tenant_id"]) != str(tenant_id)
                ):
                    raise GraphTenantViolation(
                        f"observation for asset {asset_id} names tenant {tenant_id}, "
                        f"but the asset is owned by {existing['tenant_id']}"
                    )

            cursor.execute(
                """
                INSERT INTO graph_asset_observations
                    (asset_id, scope_id, asset_type, observed_value, source,
                     parser_version, confidence, accepted, rejection_reason, tenant_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                    tenant_id = COALESCE(EXCLUDED.tenant_id, graph_asset_observations.tenant_id),
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
                    tenant_id,
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

        approved_but_undiscovered = (
            undiscovered_scope_entries(assets, authorized_scope)
            if authorized_scope is not None
            else []
        )
        discovered_but_unapproved = [
            {
                "id": asset["id"],
                "asset_type": asset["asset_type"],
                "canonical_key": asset["canonical_key"],
            }
            for asset in assets
            if not asset["in_scope"]
        ]

        with self.db_operation(
            commit=False, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                SELECT id, asset_type, observed_value, source, rejection_reason,
                       last_observed_at
                FROM graph_asset_observations
                WHERE scope_id = %s AND accepted = FALSE
                ORDER BY last_observed_at DESC
                LIMIT 100
                """,
                (scope_id,),
            )
            rejected_observations = [dict(row) for row in cursor.fetchall()]
            cursor.execute(
                """
                SELECT COUNT(*) AS rejected_count
                FROM graph_asset_observations
                WHERE scope_id = %s AND accepted = FALSE
                """,
                (scope_id,),
            )
            rejected_count = int(cursor.fetchone()["rejected_count"])

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
            "approved_but_undiscovered": approved_but_undiscovered,
            "discovered_but_unapproved": discovered_but_unapproved,
            "rejected_observations": rejected_observations,
            "rejected_observation_count": rejected_count,
            "assets": assets,
        }

    # --- coverage-driven planning (A2) ---

    def schedule_coverage_gaps(
        self,
        engagement_id: str,
        scope_id: str,
        *,
        authorized_scope: dict | str | None = None,
        priority: int = 10,
        owner: str | None = None,
    ) -> dict[str, Any]:
        """
        Convert computed coverage gaps into durable planner work (A2).

        An approved target nobody discovered cannot be tested, and an asset class
        with discovered-but-untested assets still needs recon. Both gaps become an
        exploration node on the planner frontier plus an open planner todo, so the
        next planning pass schedules them as recon instead of leaving them in a
        report.

        Idempotent: a gap that already carries a planner todo is left alone, so
        re-running against the same graph creates no duplicate node, frontier row
        or todo.
        """
        require_graph_write_owner("schedule_coverage_gaps")
        if not engagement_id or not scope_id:
            raise GraphMutationError("engagement_id and scope_id are required")

        report = self.compute_scope_coverage(
            scope_id, authorized_scope=authorized_scope
        )

        specs: list[dict[str, Any]] = []
        for gap in report["approved_but_undiscovered"]:
            gap_key = f"undiscovered_scope_entry:{gap['kind']}:{gap['value']}"
            specs.append(
                {
                    "gap_key": gap_key,
                    "gap_type": "approved_but_undiscovered",
                    "todo_type": "expand",
                    "node_kind": GraphNodeKind.INTENT,
                    "objective": f"recon approved {gap['kind']} {gap['value']}",
                    "details": {
                        "entry_kind": gap["kind"],
                        "entry_value": gap["value"],
                    },
                }
            )
        for asset_type in report["untested_asset_types"]:
            gap_key = f"untested_asset_class:{asset_type}"
            specs.append(
                {
                    "gap_key": gap_key,
                    "gap_type": "untested_asset_class",
                    "todo_type": "verify",
                    "node_kind": GraphNodeKind.HINT,
                    "objective": f"test discovered {asset_type} assets",
                    "details": {"asset_type": asset_type},
                }
            )

        existing_keys = {
            (todo.get("payload") or {}).get("coverage_gap_key")
            for todo in self.find_todos_for_engagement(engagement_id)
        }

        scheduled: list[dict[str, Any]] = []
        already_scheduled = 0
        for spec in specs:
            if spec["gap_key"] in existing_keys:
                already_scheduled += 1
                continue

            node_payload = {
                "objective": spec["objective"],
                "gap_type": spec["gap_type"],
                "coverage_gap_key": spec["gap_key"],
                **spec["details"],
            }
            with self.db_operation(
                commit=True, cursor_factory=RealDictCursor
            ) as (conn, cursor):
                cursor.execute(
                    """
                    INSERT INTO graph_nodes
                        (engagement_id, kind, payload, state, priority, origin)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (engagement_id, kind, payload) DO UPDATE SET
                        state = CASE
                            WHEN graph_nodes.state = 'cancelled' THEN EXCLUDED.state
                            ELSE graph_nodes.state
                        END,
                        priority = EXCLUDED.priority,
                        updated_at = NOW()
                    RETURNING *
                    """,
                    (
                        engagement_id,
                        spec["node_kind"],
                        Json(node_payload),
                        GraphNodeState.OPEN,
                        priority,
                        "coverage_gap",
                    ),
                )
                node = dict(cursor.fetchone())

            self.set_frontier_node(
                engagement_id,
                node["id"],
                kind=spec["node_kind"],
                priority=priority,
                frontier_reason=f"coverage gap: {spec['gap_key']}",
            )
            todo = self.create_todo(
                engagement_id,
                todo_type=spec["todo_type"],
                canonical_node_id=node["id"],
                exploration_node_id=node["id"],
                frontier_position={
                    "coverage_gap_key": spec["gap_key"],
                    "gap_type": spec["gap_type"],
                    **spec["details"],
                },
                payload={
                    "coverage_gap_key": spec["gap_key"],
                    "gap_type": spec["gap_type"],
                    "objective": spec["objective"],
                    "scope_id": scope_id,
                    **spec["details"],
                },
                owner=owner,
            )
            existing_keys.add(spec["gap_key"])
            scheduled.append(
                {
                    "gap_key": spec["gap_key"],
                    "gap_type": spec["gap_type"],
                    "node_id": node["id"],
                    "todo_id": todo["id"],
                }
            )

        logger.info(
            "Scheduled %d coverage gap(s) for engagement %s (%d already scheduled)",
            len(scheduled),
            engagement_id,
            already_scheduled,
        )
        return {
            "scope_id": scope_id,
            "gaps": len(specs),
            "scheduled": scheduled,
            "scheduled_count": len(scheduled),
            "already_scheduled": already_scheduled,
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

    # --- coverage-gap recon execution (A2) ---

    def claim_recon_todo(
        self,
        engagement_id: str,
        *,
        owner: str,
        lease_seconds: int = DEFAULT_TODO_LEASE_SECONDS,
        gap_key: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Claim the next scheduled planner todo for an engagement.

        Selection is the planner's normal frontier/todo order: highest frontier
        priority first, then oldest todo. A claim mints a random fencing token and
        a database-clock lease; an expired lease is reclaimable, so a crashed
        worker does not strand the work. A todo whose ``depends_on`` prerequisite
        has not reached ``done`` is never selected (A-10).

        The engagement filter is part of the claim, so work scheduled for one
        engagement can never be claimed for another.
        """
        require_graph_write_owner("claim_recon_todo")
        if not engagement_id or not owner:
            raise GraphMutationError("engagement_id and owner are required")
        lease_seconds = validate_lease_seconds(lease_seconds)

        gap_clause = ""
        values: list[Any] = [owner, lease_seconds, engagement_id]
        if gap_key is not None:
            gap_clause = "AND candidate.payload->>'coverage_gap_key' = %s"
            values.append(gap_key)

        with self.db_operation(
            commit=True, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                f"""
                UPDATE planner_todos AS t
                SET status = 'in_progress',
                    owner = %s,
                    started_at = NOW(),
                    claim_token = gen_random_uuid(),
                    {LEASE_GRANT_SQL},
                    attempts = t.attempts + 1,
                    updated_at = NOW()
                WHERE t.id = (
                    SELECT candidate.id
                    FROM planner_todos AS candidate
                    LEFT JOIN planner_frontier AS pf
                        ON pf.engagement_id = candidate.engagement_id
                       AND pf.node_id = candidate.exploration_node_id
                    WHERE candidate.engagement_id = %s
                      AND candidate.todo_type IN ('expand', 'verify')
                      AND candidate.payload ? 'coverage_gap_key'
                      {gap_clause}
                      AND {claimable_sql(
                          state_column="status",
                          open_states=("open",),
                          running_state="in_progress",
                          prefix="candidate.",
                      )}
                      AND (
                          candidate.depends_on IS NULL
                          OR EXISTS (
                              SELECT 1 FROM planner_todos AS prereq
                              WHERE prereq.id = candidate.depends_on
                                AND prereq.status = 'done'
                          )
                      )
                    ORDER BY COALESCE(pf.priority, 0) DESC,
                             candidate.created_at ASC,
                             candidate.id ASC
                    FOR UPDATE OF candidate SKIP LOCKED
                    LIMIT 1
                )
                RETURNING t.*
                """,
                values,
            )
            row = cursor.fetchone()
            if row is None:
                return None
            todo = dict(row)
            cursor.execute(
                """
                UPDATE planner_frontier
                SET state = 'running'
                WHERE engagement_id = %s AND node_id = %s
                """,
                (engagement_id, todo["exploration_node_id"]),
            )
            cursor.execute(
                "UPDATE graph_nodes SET state = 'running', updated_at = NOW() WHERE id = %s",
                (todo["exploration_node_id"],),
            )
            return todo

    def heartbeat_recon_todo(
        self,
        engagement_id: str,
        todo_id: str,
        *,
        claim_token: str,
        lease_seconds: int = DEFAULT_TODO_LEASE_SECONDS,
    ) -> dict[str, Any]:
        """Renew a live claim's lease; a stale token or expired lease is CLAIM_LOST."""
        require_graph_write_owner("heartbeat_recon_todo")
        if not engagement_id or not todo_id or not claim_token:
            raise GraphMutationError(
                "engagement_id, todo_id and claim_token are required"
            )
        lease_seconds = validate_lease_seconds(lease_seconds)

        with self.db_operation(
            commit=True, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                f"""
                UPDATE planner_todos
                SET {LEASE_GRANT_SQL},
                    updated_at = NOW()
                WHERE id = %s AND engagement_id = %s
                  AND {live_claim_sql(
                      state_column="status", running_state="in_progress"
                  )}
                RETURNING *
                """,
                (lease_seconds, todo_id, engagement_id, str(claim_token)),
            )
            row = cursor.fetchone()
            if row is None:
                raise GraphClaimLostError(
                    f"CLAIM_LOST: todo {todo_id} is not leased to token {claim_token}"
                )
            return dict(row)

    def complete_recon_todo(
        self,
        engagement_id: str,
        todo_id: str,
        *,
        claim_token: str | None = None,
        asset_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Close a dispatched coverage-gap todo after its recon results were ingested.

        The todo reaches ``done``, its node concludes and its frontier row is
        removed, so no orphaned frontier entry is left behind. Assets the recon
        pass produced (plus, for an untested asset class, the class's discovered
        assets) are anchored to the node and marked ``covered`` for the scope, so
        recomputed coverage no longer reports them as untested.
        """
        require_graph_write_owner("complete_recon_todo")
        if not engagement_id or not todo_id:
            raise GraphMutationError("engagement_id and todo_id are required")

        with self.db_operation(
            commit=True, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                SELECT * FROM planner_todos
                WHERE id = %s AND engagement_id = %s
                FOR UPDATE
                """,
                (todo_id, engagement_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise GraphMutationError(
                    f"todo {todo_id} is not part of engagement {engagement_id}"
                )
            todo = dict(row)
            if todo["status"] not in (TodoStatus.OPEN, TodoStatus.IN_PROGRESS):
                raise GraphMutationError(
                    f"todo {todo_id} is {todo['status']}; only open/in_progress work can complete"
                )
            stored_token = todo.get("claim_token")
            if not claim_token_matches(stored_token, claim_token):
                raise GraphClaimLostError(
                    f"CLAIM_LOST: todo {todo_id} is not leased to token {claim_token}"
                )

            payload = todo.get("payload") or {}
            scope_id = payload.get("scope_id") or engagement_id
            node_id = todo["exploration_node_id"]
            covered_ids = {str(asset_id) for asset_id in (asset_ids or [])}
            if payload.get("gap_type") == "untested_asset_class" and payload.get(
                "asset_type"
            ):
                cursor.execute(
                    "SELECT id FROM graph_assets WHERE scope_id = %s AND asset_type = %s",
                    (scope_id, payload["asset_type"]),
                )
                covered_ids.update(str(found["id"]) for found in cursor.fetchall())

            covered_count = 0
            if node_id is not None:
                for asset_id in sorted(covered_ids):
                    # Anchoring through a scope-filtered SELECT means an asset
                    # id from another scope is never pulled into this scope.
                    cursor.execute(
                        """
                        INSERT INTO graph_anchors (node_id, asset_id, role)
                        SELECT %s, id, 'tested' FROM graph_assets
                        WHERE id = %s AND scope_id = %s
                        ON CONFLICT (node_id, asset_id, role) DO UPDATE SET
                            created_at = NOW()
                        RETURNING id
                        """,
                        (node_id, asset_id, scope_id),
                    )
                    anchor = cursor.fetchone()
                    if anchor is None:
                        continue
                    cursor.execute(
                        """
                        INSERT INTO graph_anchor_scopes
                            (anchor_id, scope_id, incorporated_by, coverage_state,
                             incorporated_at)
                        VALUES (%s, %s, %s, 'covered', NOW())
                        ON CONFLICT (anchor_id, scope_id) DO UPDATE SET
                            coverage_state = 'covered',
                            incorporated_by = COALESCE(
                                EXCLUDED.incorporated_by,
                                graph_anchor_scopes.incorporated_by
                            ),
                            incorporated_at = COALESCE(
                                graph_anchor_scopes.incorporated_at, NOW()
                            ),
                            updated_at = NOW()
                        """,
                        # incorporated_by is a UUID column; the todo owner is a
                        # worker identifier, so attribution stays on the todo.
                        (anchor["id"], scope_id, None),
                    )
                    covered_count += 1

                cursor.execute(
                    "UPDATE graph_nodes SET state = 'concluded', updated_at = NOW() WHERE id = %s",
                    (node_id,),
                )
                cursor.execute(
                    "DELETE FROM planner_frontier WHERE engagement_id = %s AND node_id = %s",
                    (engagement_id, node_id),
                )

            cursor.execute(
                f"""
                UPDATE planner_todos
                SET status = 'done',
                    completed_at = NOW(),
                    {LEASE_CLEAR_SQL},
                    updated_at = NOW()
                WHERE id = %s
                RETURNING *
                """,
                (todo_id,),
            )
            completed = dict(cursor.fetchone())
            completed["covered_asset_count"] = covered_count
            return completed

    def release_recon_todo(
        self,
        engagement_id: str,
        todo_id: str,
        *,
        claim_token: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any] | None:
        """Release a claimed todo back to the frontier after a dispatch failure."""
        require_graph_write_owner("release_recon_todo")
        if not engagement_id or not todo_id:
            raise GraphMutationError("engagement_id and todo_id are required")
        with self.db_operation(
            commit=True, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                SELECT claim_token FROM planner_todos
                WHERE id = %s AND engagement_id = %s
                FOR UPDATE
                """,
                (todo_id, engagement_id),
            )
            current = cursor.fetchone()
            if current is None:
                return None
            if not claim_token_matches(current["claim_token"], claim_token):
                raise GraphClaimLostError(
                    f"CLAIM_LOST: todo {todo_id} is not leased to token {claim_token}"
                )
            cursor.execute(
                f"""
                UPDATE planner_todos
                SET status = 'open',
                    owner = NULL,
                    started_at = NULL,
                    {LEASE_CLEAR_SQL},
                    updated_at = NOW()
                WHERE id = %s AND engagement_id = %s AND status = 'in_progress'
                RETURNING *
                """,
                (todo_id, engagement_id),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            todo = dict(row)
            cursor.execute(
                "UPDATE graph_nodes SET state = 'open', updated_at = NOW() WHERE id = %s",
                (todo["exploration_node_id"],),
            )
            cursor.execute(
                """
                UPDATE planner_frontier
                SET state = 'open'
                WHERE engagement_id = %s AND node_id = %s
                """,
                (engagement_id, todo["exploration_node_id"]),
            )
            if reason:
                logger.warning(
                    "Released recon todo %s for engagement %s: %s",
                    todo_id,
                    engagement_id,
                    reason,
                )
            return todo

    # --- planner turns and typed intent proposals (A3) ---

    def begin_planner_turn(
        self, engagement_id: str, *, trigger: str = "outbox"
    ) -> dict[str, Any]:
        """Record the start of one planning turn; returns the turn row."""
        require_graph_write_owner("begin_planner_turn")
        if not engagement_id:
            raise GraphMutationError("engagement_id is required")
        with self.db_operation(
            commit=True, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                INSERT INTO planner_turns (engagement_id, trigger, status)
                VALUES (%s, %s, 'running')
                RETURNING *
                """,
                (engagement_id, trigger),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("planner_turns insert did not return a row")
            return dict(row)

    def consume_planner_events(
        self,
        engagement_id: str,
        turn_id: str,
        *,
        scope_type: str = "graph",
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """
        Claim every queued outbox event for an engagement into one planning turn.

        The whole burst is consumed atomically (debounce/coalesce): one turn sees
        all queued rows and each row records the turn that consumed it. Events
        that arrive after this call wait for the next turn, and a later loop pass
        finds any wake that happened while no consumer was running.
        """
        require_graph_write_owner("consume_planner_events")
        if not engagement_id or not turn_id:
            raise GraphMutationError("engagement_id and turn_id are required")
        with self.db_operation(
            commit=True, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                UPDATE graph_outbox
                SET status = 'dequeued',
                    dequeued_at = NOW(),
                    attempts = attempts + 1,
                    planner_turn_id = %s,
                    updated_at = NOW()
                WHERE id IN (
                    SELECT id FROM graph_outbox
                    WHERE scope_type = %s AND scope_id = %s AND status = 'queued'
                    ORDER BY created_at ASC
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING *
                """,
                (turn_id, scope_type, engagement_id, limit),
            )
            return [dict(row) for row in cursor.fetchall()]

    def complete_planner_turn(
        self,
        turn_id: str,
        *,
        events_consumed: int,
        proposals_received: int,
        intents_created: int,
        duplicates_suppressed: int,
    ) -> dict[str, Any]:
        """Mark a planning turn completed with its counts."""
        require_graph_write_owner("complete_planner_turn")
        if not turn_id:
            raise GraphMutationError("turn_id is required")
        with self.db_operation(
            commit=True, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                UPDATE planner_turns
                SET status = 'completed',
                    events_consumed = %s,
                    proposals_received = %s,
                    intents_created = %s,
                    duplicates_suppressed = %s,
                    completed_at = NOW()
                WHERE id = %s
                RETURNING *
                """,
                (
                    events_consumed,
                    proposals_received,
                    intents_created,
                    duplicates_suppressed,
                    turn_id,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                raise GraphMutationError(f"planner turn {turn_id} does not exist")
            return dict(row)

    def fail_planner_turn(self, turn_id: str, error: str) -> dict[str, Any]:
        """Mark a planning turn failed and record why (never a silent no-op)."""
        require_graph_write_owner("fail_planner_turn")
        if not turn_id:
            raise GraphMutationError("turn_id is required")
        with self.db_operation(
            commit=True, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                UPDATE planner_turns
                SET status = 'failed', error = %s, completed_at = NOW()
                WHERE id = %s
                RETURNING *
                """,
                (error, turn_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise GraphMutationError(f"planner turn {turn_id} does not exist")
            return dict(row)

    def find_planner_turns(
        self, engagement_id: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        """List recent planning turns for an engagement (newest first)."""
        with self.db_operation(
            commit=False, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                SELECT * FROM planner_turns
                WHERE engagement_id = %s
                ORDER BY started_at DESC, id DESC
                LIMIT %s
                """,
                (engagement_id, limit),
            )
            return [dict(row) for row in cursor.fetchall()]

    def count_queued_outbox(
        self, engagement_id: str, *, scope_type: str = "graph"
    ) -> int:
        """Count outbox events still waiting for a planning turn."""
        with self.db_operation(
            commit=False, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                SELECT COUNT(*) AS queued FROM graph_outbox
                WHERE scope_type = %s AND scope_id = %s AND status = 'queued'
                """,
                (scope_type, engagement_id),
            )
            return int(cursor.fetchone()["queued"])

    def planner_overview(self, engagement_id: str) -> dict[str, Any]:
        """Read the bounded planner snapshot for an engagement."""
        if not engagement_id:
            raise GraphMutationError("engagement_id is required")
        with self.db_operation(
            commit=False, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                SELECT * FROM graph_nodes
                WHERE engagement_id = %s AND kind = 'goal'
                ORDER BY created_at ASC
                """,
                (engagement_id,),
            )
            goals = [dict(row) for row in cursor.fetchall()]

            cursor.execute(
                """
                SELECT * FROM graph_nodes
                WHERE engagement_id = %s AND kind = 'intent'
                  AND state IN ('open', 'running')
                ORDER BY created_at ASC
                """,
                (engagement_id,),
            )
            open_intents = [dict(row) for row in cursor.fetchall()]

            cursor.execute(
                """
                SELECT * FROM graph_nodes
                WHERE engagement_id = %s AND kind = 'fact'
                  AND state != 'cancelled'
                ORDER BY created_at DESC
                LIMIT 100
                """,
                (engagement_id,),
            )
            facts = [dict(row) for row in cursor.fetchall()]

            cursor.execute(
                """
                SELECT a.id, a.canonical_key, a.asset_type, a.display_value,
                       a.parent_asset_id
                FROM graph_assets AS a
                WHERE a.scope_id = %s
                  AND NOT EXISTS (
                      SELECT 1
                      FROM graph_anchors AS ga
                      JOIN graph_anchor_scopes AS s ON s.anchor_id = ga.id
                      WHERE ga.asset_id = a.id
                        AND s.scope_id = %s
                        AND s.coverage_state IN ('incorporated', 'covered')
                  )
                ORDER BY a.asset_type, a.canonical_key
                LIMIT 50
                """,
                (engagement_id, engagement_id),
            )
            untested_assets = [dict(row) for row in cursor.fetchall()]

            cursor.execute(
                """
                SELECT COUNT(*) AS open_todos FROM planner_todos
                WHERE engagement_id = %s AND status IN ('open', 'in_progress')
                """,
                (engagement_id,),
            )
            open_todos = int(cursor.fetchone()["open_todos"])

        return {
            "engagement_id": engagement_id,
            "goals": goals,
            "open_intents": open_intents,
            "facts": facts,
            "untested_assets": untested_assets,
            "open_todo_count": open_todos,
        }

    def apply_intent_proposals(
        self, engagement_id: str, proposals: list[IntentProposal]
    ) -> dict[str, Any]:
        """
        Validate and persist typed intent proposals (A-07/A-09).

        Every proposal is validated before anything is written: unknown or
        out-of-scope target assets and unknown source facts reject the whole
        batch. Duplicates are suppressed against any node already carrying the
        intent's stable key (an open/running intent, a concluded intent or a fact
        that already records the evidence), so the same intent is never created
        twice.
        """
        require_graph_write_owner("apply_intent_proposals")
        if not engagement_id:
            raise GraphMutationError("engagement_id is required")

        proposals = list(proposals or [])
        validated: list[IntentProposal] = []
        for proposal in proposals:
            if not isinstance(proposal, IntentProposal):
                raise IntentProposalError(
                    f"expected IntentProposal, got {type(proposal).__name__}"
                )
            validated.append(proposal.validated())
        if not validated:
            return {"created": [], "suppressed": [], "proposals_received": 0}

        with self.db_operation(
            commit=True, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            for proposal in validated:
                cursor.execute(
                    "SELECT id::text AS id FROM graph_assets "
                    "WHERE id::text = ANY(%s) AND scope_id = %s",
                    (list(proposal.target_asset_ids), engagement_id),
                )
                in_scope = {row["id"] for row in cursor.fetchall()}
                missing = set(proposal.target_asset_ids) - in_scope
                if missing:
                    raise GraphMutationError(
                        "intent target asset(s) outside engagement scope "
                        f"{engagement_id}: {sorted(missing)}"
                    )

                if proposal.from_fact_ids:
                    cursor.execute(
                        "SELECT id::text AS id FROM graph_nodes "
                        "WHERE id::text = ANY(%s) AND engagement_id = %s "
                        "AND kind = 'fact'",
                        (list(proposal.from_fact_ids), engagement_id),
                    )
                    known_facts = {row["id"] for row in cursor.fetchall()}
                    unknown_facts = set(proposal.from_fact_ids) - known_facts
                    if unknown_facts:
                        raise GraphMutationError(
                            "intent references facts that are not this "
                            f"engagement's facts: {sorted(unknown_facts)}"
                        )

                if proposal.goal_node_id:
                    cursor.execute(
                        "SELECT id FROM graph_nodes "
                        "WHERE id = %s AND engagement_id = %s AND kind = 'goal'",
                        (proposal.goal_node_id, engagement_id),
                    )
                    if cursor.fetchone() is None:
                        raise GraphMutationError(
                            "intent goal_node_id is not a goal of engagement "
                            f"{engagement_id}"
                        )

            keys = [proposal.intent_key() for proposal in validated]
            cursor.execute(
                """
                SELECT id, kind, state, payload
                FROM graph_nodes
                WHERE engagement_id = %s
                  AND payload->>'intent_key' = ANY(%s)
                """,
                (engagement_id, keys),
            )
            existing = {}
            for row in cursor.fetchall():
                key = (row["payload"] or {}).get("intent_key")
                if key and key not in existing:
                    existing[key] = dict(row)

            created: list[dict[str, Any]] = []
            suppressed: list[dict[str, Any]] = []
            for proposal in validated:
                key = proposal.intent_key()
                duplicate = existing.get(key)
                if duplicate is not None:
                    reason = (
                        "open_intent"
                        if duplicate["kind"] == GraphNodeKind.INTENT
                        and duplicate["state"] in ("open", "running")
                        else "existing_evidence"
                    )
                    suppressed.append(
                        {
                            "intent_key": key,
                            "reason": reason,
                            "node_id": str(duplicate["id"]),
                        }
                    )
                    continue

                cursor.execute(
                    """
                    INSERT INTO graph_nodes
                        (engagement_id, kind, payload, state, priority, origin)
                    VALUES (%s, 'intent', %s, 'open', %s, 'planner')
                    ON CONFLICT (engagement_id, kind, payload) DO NOTHING
                    RETURNING *
                    """,
                    (engagement_id, Json(proposal.to_payload()), proposal.priority),
                )
                inserted = cursor.fetchone()
                if inserted is None:
                    # A concurrent drain committed the same intent between our
                    # duplicate check and insert. Suppress it instead of failing.
                    cursor.execute(
                        "SELECT id FROM graph_nodes WHERE engagement_id = %s "
                        "AND kind = 'intent' AND payload->>'intent_key' = %s",
                        (engagement_id, key),
                    )
                    winner = cursor.fetchone()
                    suppressed.append(
                        {
                            "intent_key": key,
                            "reason": "concurrent_duplicate",
                            "node_id": str(winner["id"]) if winner else None,
                        }
                    )
                    continue
                node = dict(inserted)

                for asset_id in proposal.target_asset_ids:
                    cursor.execute(
                        """
                        INSERT INTO graph_anchors (node_id, asset_id, role)
                        SELECT %s, id, 'targets' FROM graph_assets
                        WHERE id = %s AND scope_id = %s
                        ON CONFLICT (node_id, asset_id, role) DO UPDATE SET
                            created_at = NOW()
                        RETURNING id
                        """,
                        (node["id"], asset_id, engagement_id),
                    )
                    if cursor.fetchone() is None:
                        raise GraphMutationError(
                            f"target asset {asset_id} left the engagement scope "
                            "while the intent was being written"
                        )

                existing[key] = node
                created.append(node)

        return {
            "created": created,
            "suppressed": suppressed,
            "proposals_received": len(validated),
        }

    # --- worker protocol: action ledger, traces, intent claims, proofs ---

    def record_action(
        self,
        engagement_id: str,
        action_id: str,
        *,
        intent_node_id: str | None = None,
        worker_id: str | None = None,
        tool: str | None = None,
        canonical_arguments: dict[str, Any] | None = None,
        outcome: str = "completed",
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Record one worker action/result exactly once (A-16).

        ``(engagement_id, action_id)`` is unique. Re-delivering the same action
        returns ``recorded=False`` and the originally committed result, so a
        replay never creates a second logical graph update.
        """
        require_graph_write_owner("record_action")
        if not engagement_id or not action_id:
            raise GraphMutationError("engagement_id and action_id are required")
        with self.db_operation(
            commit=True, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                INSERT INTO graph_actions
                    (engagement_id, action_id, intent_node_id, worker_id, tool,
                     canonical_arguments, outcome, result)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (engagement_id, action_id) DO NOTHING
                RETURNING *
                """,
                (
                    engagement_id,
                    action_id,
                    intent_node_id,
                    worker_id,
                    tool,
                    Json(canonical_arguments or {}),
                    outcome,
                    Json(result or {}),
                ),
            )
            row = cursor.fetchone()
            recorded = row is not None
            if row is None:
                cursor.execute(
                    "SELECT * FROM graph_actions "
                    "WHERE engagement_id = %s AND action_id = %s",
                    (engagement_id, action_id),
                )
                row = cursor.fetchone()
            if row is None:
                raise RuntimeError("graph_actions upsert did not return a row")
            return {"recorded": recorded, "action": dict(row)}

    def find_action(
        self, engagement_id: str, action_id: str
    ) -> dict[str, Any] | None:
        """Read a recorded action/result, if any."""
        with self.db_operation(
            commit=False, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                "SELECT * FROM graph_actions "
                "WHERE engagement_id = %s AND action_id = %s",
                (engagement_id, action_id),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def record_trace(
        self,
        engagement_id: str,
        summary: str,
        *,
        intent_node_id: str | None = None,
        worker_id: str | None = None,
        tool: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Store a redacted, engagement-scoped trace summary for reuse (A-13)."""
        require_graph_write_owner("record_trace")
        cleaned = sanitize_untrusted_text(summary)
        if not engagement_id or not cleaned:
            raise GraphMutationError("engagement_id and a non-empty summary are required")
        with self.db_operation(
            commit=True, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                INSERT INTO graph_traces
                    (engagement_id, intent_node_id, worker_id, tool, summary, payload)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    engagement_id,
                    intent_node_id,
                    worker_id,
                    tool,
                    cleaned,
                    Json(payload or {}),
                ),
            )
            return dict(cursor.fetchone())

    def search_traces(
        self,
        engagement_id: str,
        *,
        query: str | None = None,
        intent_node_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Search trace summaries for one engagement only (A-13/A-14).

        Another worker's trace is reusable data, so every row is returned with
        ``trust: untrusted`` and a sanitised summary, never as an instruction.
        """
        if not engagement_id:
            raise GraphMutationError("engagement_id is required")
        clauses = ["engagement_id = %s"]
        values: list[Any] = [engagement_id]
        if intent_node_id is not None:
            clauses.append("intent_node_id = %s")
            values.append(intent_node_id)
        if query:
            clauses.append("(summary ILIKE %s OR tool ILIKE %s)")
            pattern = f"%{query}%"
            values.extend([pattern, pattern])
        with self.db_operation(
            commit=False, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                f"SELECT * FROM graph_traces WHERE {' AND '.join(clauses)} "
                "ORDER BY created_at DESC LIMIT %s",
                values + [max(1, min(int(limit), 100))],
            )
            traces = []
            for row in cursor.fetchall():
                trace = dict(row)
                trace["summary"] = sanitize_untrusted_text(trace["summary"])
                trace["trust"] = "untrusted"
                traces.append(trace)
            return traces

    def record_write_rejection(
        self,
        engagement_id: str | None,
        operation: str,
        reason: str,
        *,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record a rejected graph write for audit before re-raising (A-05)."""
        require_graph_write_owner("record_write_rejection")
        with self.db_operation(
            commit=True, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                INSERT INTO graph_write_rejections
                    (engagement_id, operation, reason, detail)
                VALUES (%s, %s, %s, %s)
                RETURNING *
                """,
                (engagement_id, operation, sanitize_untrusted_text(reason, limit=1000), Json(detail or {})),
            )
            return dict(cursor.fetchone())

    def claim_intent_node(
        self,
        engagement_id: str,
        worker_id: str,
        *,
        intent_node_id: str | None = None,
        lease_seconds: int = _INTENT_LEASE_SECONDS,
    ) -> dict[str, Any] | None:
        """
        Claim exactly one open intent for a worker (A4).

        A worker may hold at most one live intent: asking for another while its
        lease is live raises instead of double-routing. The claim carries a
        random fencing token and a database-clock lease, so an expired claim is
        reclaimable while stale writes are rejected.
        """
        require_graph_write_owner("claim_intent_node")
        if not engagement_id or not worker_id:
            raise GraphMutationError("engagement_id and worker_id are required")
        lease_seconds = validate_lease_seconds(lease_seconds)

        with self.db_operation(
            commit=True, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                SELECT id FROM graph_nodes
                WHERE engagement_id = %s AND kind = 'intent' AND state = 'running'
                  AND owner = %s AND lease_expires_at > NOW()
                """,
                (engagement_id, worker_id),
            )
            held = cursor.fetchone()
            if held is not None:
                if intent_node_id and str(held["id"]) != str(intent_node_id):
                    raise GraphMutationError(
                        f"worker {worker_id} already holds live intent {held['id']}"
                    )
                cursor.execute("SELECT * FROM graph_nodes WHERE id = %s", (held["id"],))
                return dict(cursor.fetchone())

            cursor.execute(
                f"""
                UPDATE graph_nodes
                SET state = 'running', owner = %s,
                    claim_token = gen_random_uuid(),
                    {LEASE_GRANT_SQL}, updated_at = NOW()
                WHERE id = (
                    SELECT id FROM graph_nodes
                    WHERE engagement_id = %s AND kind = 'intent'
                      AND (%s::uuid IS NULL OR id = %s::uuid)
                      AND {claimable_sql()}
                    ORDER BY priority DESC, created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING *
                """,
                (worker_id, lease_seconds, engagement_id, intent_node_id, intent_node_id),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def heartbeat_intent_node(
        self,
        engagement_id: str,
        intent_node_id: str,
        *,
        claim_token: str,
        lease_seconds: int = _INTENT_LEASE_SECONDS,
    ) -> dict[str, Any]:
        """Renew a worker's live intent claim; a stale token is CLAIM_LOST."""
        require_graph_write_owner("heartbeat_intent_node")
        if not engagement_id or not intent_node_id or not claim_token:
            raise GraphMutationError(
                "engagement_id, intent_node_id and claim_token are required"
            )
        lease_seconds = validate_lease_seconds(lease_seconds)
        with self.db_operation(
            commit=True, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                f"""
                UPDATE graph_nodes
                SET {LEASE_GRANT_SQL}, updated_at = NOW()
                WHERE engagement_id = %s AND id = %s AND kind = 'intent'
                  AND {live_claim_sql()}
                RETURNING *
                """,
                (lease_seconds, engagement_id, intent_node_id, claim_token),
            )
            row = cursor.fetchone()
            if row is None:
                raise GraphClaimLostError(
                    f"intent {intent_node_id} claim token is expired or no longer current"
                )
            return dict(row)

    def complete_intent_node(
        self,
        engagement_id: str,
        intent_node_id: str,
        *,
        claim_token: str,
        fact_description: str,
    ) -> dict[str, Any]:
        """
        Close a claimed intent with exactly one conclusion fact (CAIRN explore).

        The token must still match and the lease must be live. The fact and the
        ``yields`` edge are committed with the intent transition in one
        transaction, and the fact payload is stable per intent so a repeated
        conclusion cannot create a second fact.
        """
        require_graph_write_owner("complete_intent_node")
        description = sanitize_untrusted_text(fact_description, limit=1000)
        if not description:
            raise GraphMutationError("fact_description is required")
        with self.db_operation(
            commit=True, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                f"""
                SELECT * FROM graph_nodes
                WHERE engagement_id = %s AND id = %s AND kind = 'intent'
                  AND {live_claim_sql()}
                FOR UPDATE
                """,
                (engagement_id, intent_node_id, claim_token),
            )
            intent = cursor.fetchone()
            if intent is None:
                raise GraphClaimLostError(
                    f"intent {intent_node_id} claim token is expired or no longer current"
                )

            payload = {"intent_node_id": str(intent_node_id), "summary": description}
            cursor.execute(
                """
                INSERT INTO graph_nodes
                    (engagement_id, kind, payload, state, origin, source_task_id)
                VALUES (%s, 'fact', %s, 'open', 'worker', %s)
                ON CONFLICT (engagement_id, kind, payload) DO UPDATE SET
                    updated_at = NOW()
                RETURNING *
                """,
                (engagement_id, Json(payload), intent_node_id),
            )
            fact = dict(cursor.fetchone())

            cursor.execute(
                """
                INSERT INTO graph_node_edges
                    (engagement_id, source_node_id, target_node_id, edge_type)
                VALUES (%s, %s, %s, 'yields')
                ON CONFLICT (source_node_id, target_node_id, edge_type) DO NOTHING
                """,
                (engagement_id, intent_node_id, fact["id"]),
            )

            cursor.execute(
                f"""
                UPDATE graph_nodes
                SET state = 'concluded', {LEASE_CLEAR_SQL}, updated_at = NOW()
                WHERE id = %s
                RETURNING *
                """,
                (intent_node_id,),
            )
            concluded = dict(cursor.fetchone())

        return {"intent": concluded, "fact": fact}

    def worker_intent_package(
        self,
        engagement_id: str,
        intent_node_id: str,
        *,
        trace_limit: int = 5,
    ) -> dict[str, Any]:
        """
        Build the bounded payload a worker receives for one claimed intent (A4).

        It contains the intent, its anchored target assets, the facts its
        proposal was derived from, and a few redacted trace summaries other
        workers already produced. It contains no scope-widening authority: the
        package is read-only and the dispatcher remains the only writer.
        """
        with self.db_operation(
            commit=False, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                "SELECT * FROM graph_nodes WHERE engagement_id = %s AND id = %s "
                "AND kind = 'intent'",
                (engagement_id, intent_node_id),
            )
            intent = cursor.fetchone()
            if intent is None:
                raise GraphMutationError(
                    f"intent {intent_node_id} is not an intent of engagement {engagement_id}"
                )
            intent = dict(intent)

            cursor.execute(
                """
                SELECT a.id, a.canonical_key, a.asset_type, a.display_value
                FROM graph_anchors AS ga
                JOIN graph_assets AS a ON a.id = ga.asset_id
                WHERE ga.node_id = %s AND ga.role = 'targets'
                ORDER BY a.canonical_key
                """,
                (intent_node_id,),
            )
            assets = [dict(row) for row in cursor.fetchall()]

        fact_ids = [str(v) for v in (intent.get("payload") or {}).get("from_fact_ids", [])]
        facts: list[dict[str, Any]] = []
        if fact_ids:
            with self.db_operation(
                commit=False, cursor_factory=RealDictCursor
            ) as (conn, cursor):
                cursor.execute(
                    "SELECT id, payload, state FROM graph_nodes "
                    "WHERE engagement_id = %s AND kind = 'fact' "
                    "AND id::text = ANY(%s)",
                    (engagement_id, fact_ids),
                )
                facts = [dict(row) for row in cursor.fetchall()]

        return {
            "engagement_id": engagement_id,
            "intent": intent,
            # The goal this intent was proposed for. The worker stamps it on
            # the findings it produces, so the goal proof is deterministic even
            # when the engagement has several open goals.
            "goal_node_id": (intent.get("payload") or {}).get("goal_node_id"),
            "assets": assets,
            "prerequisite_facts": facts,
            "traces": self.search_traces(
                engagement_id, intent_node_id=intent_node_id, limit=trace_limit
            ),
            "write_authority": "dispatcher-only",
            "one_intent_per_worker": True,
        }

    def prove_goal_from_findings(
        self,
        engagement_id: str,
        goal_id: str,
        finding_ids: list[str],
        *,
        proof_summary: str = "",
    ) -> dict[str, Any]:
        """
        Prove a goal only from findings a verifier actually proved (A-08).

        Each referenced ``findings`` row must belong to the engagement, be in a
        verified terminal state (CONFIRMED/VERIFIED), **and** carry verifier
        provenance in its ``evidence`` — see :func:`verifier_provenance_error`.
        A row whose status merely says CONFIRMED (hand-inserted, promoted by
        confidence, or marked by an analyst) cannot conclude a goal. Only when
        both hold does the dispatcher create/refresh the graph finding node, add
        a ``proves`` edge and conclude the goal. An unproven or foreign finding
        rejects the whole proof before any write.
        """
        require_graph_write_owner("prove_goal_from_findings")
        if not engagement_id or not goal_id or not finding_ids:
            raise GraphMutationError(
                "engagement_id, goal_id and at least one verified finding are required"
            )
        summary = sanitize_untrusted_text(proof_summary, limit=1000)
        with self.db_operation(
            commit=True, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                "SELECT * FROM graph_nodes WHERE engagement_id = %s AND id = %s "
                "AND kind = 'goal'",
                (engagement_id, goal_id),
            )
            goal = cursor.fetchone()
            if goal is None:
                raise GraphMutationError(
                    f"goal {goal_id} is not a goal of engagement {engagement_id}"
                )

            finding_nodes: list[dict[str, Any]] = []
            for finding_id in finding_ids:
                cursor.execute(
                    "SELECT id, title, severity, status, evidence FROM findings "
                    "WHERE engagement_id = %s AND id = %s",
                    (engagement_id, finding_id),
                )
                finding = cursor.fetchone()
                if finding is None:
                    raise GraphMutationError(
                        f"finding {finding_id} is not a finding of engagement {engagement_id}"
                    )
                if str(finding["status"]).upper() not in ("CONFIRMED", "VERIFIED"):
                    raise GraphMutationError(
                        f"finding {finding_id} is not verified "
                        f"(status={finding['status']}); it cannot prove a goal"
                    )
                provenance_error = verifier_provenance_error(finding["evidence"])
                if provenance_error is not None:
                    raise GraphMutationError(
                        f"finding {finding_id} has no verifier proof "
                        f"(status={finding['status']} is a claim, not proof): "
                        f"{provenance_error}"
                    )

                payload = {
                    "finding_id": str(finding["id"]),
                    "title": sanitize_untrusted_text(finding["title"], limit=200),
                    "severity": finding["severity"],
                }
                cursor.execute(
                    """
                    INSERT INTO graph_nodes (engagement_id, kind, payload, state, origin)
                    VALUES (%s, 'finding', %s, 'verified', 'verifier')
                    ON CONFLICT (engagement_id, kind, payload) DO UPDATE SET
                        state = 'verified', updated_at = NOW()
                    RETURNING *
                    """,
                    (engagement_id, Json(payload)),
                )
                finding_node = dict(cursor.fetchone())
                finding_nodes.append(finding_node)

                cursor.execute(
                    """
                    INSERT INTO graph_node_edges
                        (engagement_id, source_node_id, target_node_id, edge_type)
                    VALUES (%s, %s, %s, 'proves')
                    ON CONFLICT (source_node_id, target_node_id, edge_type) DO NOTHING
                    """,
                    (engagement_id, finding_node["id"], goal_id),
                )

            cursor.execute(
                """
                UPDATE graph_nodes
                SET state = 'concluded',
                    payload = payload || %s::jsonb,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING *
                """,
                (
                    Json(
                        {
                            "proof": {
                                "finding_ids": [str(v) for v in finding_ids],
                                "summary": summary,
                            }
                        }
                    ),
                    goal_id,
                ),
            )
            concluded = dict(cursor.fetchone())

        return {
            "goal": concluded,
            "finding_nodes": finding_nodes,
            "proves_edges": len(finding_nodes),
        }

    def find_engagements_with_queued_outbox(
        self, *, limit: int = 100, scope_type: str = "graph"
    ) -> list[str]:
        """List engagement ids that still have queued outbox work (production drain)."""
        with self.db_operation(
            commit=False, cursor_factory=RealDictCursor
        ) as (conn, cursor):
            cursor.execute(
                """
                SELECT DISTINCT scope_id
                FROM graph_outbox
                WHERE scope_type = %s AND status = 'queued'
                ORDER BY scope_id
                LIMIT %s
                """,
                (scope_type, limit),
            )
            return [str(row["scope_id"]) for row in cursor.fetchall()]

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


# ---------------------------------------------------------------------------
# Read-only engagement ownership lookups
# ---------------------------------------------------------------------------


def load_authorized_scope(scope_id: str) -> dict | str | None:
    """
    Read the engagement's ``authorized_scope`` column (read-only).

    Returns None when the row or column is missing, which means there is no
    approved scope to compare against.
    """
    try:
        from database.connection import db_cursor

        with db_cursor() as cursor:
            cursor.execute(
                "SELECT authorized_scope FROM engagements WHERE id = %s", (scope_id,)
            )
            row = cursor.fetchone()
            return row[0] if row else None
    except Exception as exc:  # noqa: BLE001 - ownership lookup must not break reads
        logger.warning(
            "Could not load authorized_scope for scope %s: %s", scope_id, exc
        )
        return None


def resolve_scope_tenant(scope_id: str) -> str | None:
    """
    Return the tenant (``engagements.org_id``) that owns a scope (read-only).

    Returns None when the engagement row or org_id is unavailable, in which case
    there is no known owner to enforce against.
    """
    try:
        from database.connection import db_cursor

        with db_cursor() as cursor:
            cursor.execute(
                "SELECT org_id FROM engagements WHERE id = %s", (scope_id,)
            )
            row = cursor.fetchone()
            return str(row[0]) if row and row[0] is not None else None
    except Exception as exc:  # noqa: BLE001 - ownership lookup must not break reads
        logger.warning("Could not resolve tenant for scope %s: %s", scope_id, exc)
        return None
