"""
Trusted graph ingestion: raw observations -> canonical assets (A2).

Recon/tool output enters the asset graph only through this module. It
canonicalizes the observed value, enforces the engagement's authorized scope,
links the parent asset, and records the raw observation so two tools reporting
the same asset merge onto one canonical row instead of duplicating it.

Ingestion is trusted dispatcher code. It still goes through
``DispatcherGraph.ingest_observation`` because every graph write is
dispatcher-owned (C-18).
"""

from __future__ import annotations

from typing import Any

from database.graph_identity import (
    AssetIdentityError,
    asset_in_scope,
    canonicalize_asset,
)
from database.graph_repository import ExplorationGraphRepository, GraphMutationError

REJECTION_OUT_OF_SCOPE = "out_of_scope"


class GraphIngestionError(GraphMutationError):
    """A raw observation could not be ingested as a canonical asset."""


class GraphIngestor:
    """Convert structured observations into canonical assets and observations."""

    def __init__(self, repository: ExplorationGraphRepository) -> None:
        self._repo = repository

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
        Ingest one raw observation.

        Returns a dict with:
          - ``accepted``: whether the observation may enter the usable graph
          - ``asset``: the canonical asset row, or None when rejected
          - ``observation``: the recorded observation row
          - ``canonical_key`` / ``rejection_reason``
        """
        if not isinstance(source, str) or not source.strip():
            raise GraphIngestionError("source is required")
        if confidence is not None and not 0.0 <= float(confidence) <= 1.0:
            raise GraphIngestionError("confidence must be between 0 and 1")

        try:
            identity = canonicalize_asset(asset_type, observed_value)
        except AssetIdentityError as exc:
            raise GraphIngestionError(str(exc)) from exc

        if not asset_in_scope(
            identity.asset_type, identity.canonical_key, authorized_scope
        ):
            observation = self._repo.record_asset_observation(
                asset_id=None,
                asset_type=identity.asset_type,
                observed_value=observed_value.strip(),
                source=source.strip(),
                scope_id=scope_id,
                parser_version=parser_version,
                confidence=confidence,
                accepted=False,
                rejection_reason=REJECTION_OUT_OF_SCOPE,
            )
            return {
                "accepted": False,
                "asset": None,
                "observation": observation,
                "canonical_key": identity.canonical_key,
                "rejection_reason": REJECTION_OUT_OF_SCOPE,
            }

        parent_asset = self._ensure_parent(
            identity.parent,
            scope_id=scope_id,
            authorized_scope=authorized_scope,
            source=source,
            create_parents=create_parents,
        )

        asset = self._repo.upsert_asset(
            identity.canonical_key,
            identity.asset_type,
            display_value=identity.display_value,
            scope_id=scope_id,
            metadata={"last_source": source.strip()},
            parent_asset_id=parent_asset["id"] if parent_asset else None,
            parent_relationship="child_of" if parent_asset else None,
        )

        observation = self._repo.record_asset_observation(
            asset_id=asset["id"],
            asset_type=identity.asset_type,
            observed_value=observed_value.strip(),
            source=source.strip(),
            scope_id=scope_id,
            parser_version=parser_version,
            confidence=confidence,
            accepted=True,
        )

        return {
            "accepted": True,
            "asset": asset,
            "observation": observation,
            "canonical_key": identity.canonical_key,
            "rejection_reason": None,
        }

    def _ensure_parent(
        self,
        parent,
        *,
        scope_id: str | None,
        authorized_scope: dict | str | None,
        source: str,
        create_parents: bool,
    ) -> dict[str, Any] | None:
        if parent is None or not create_parents:
            return None
        if not asset_in_scope(parent.asset_type, parent.canonical_key, authorized_scope):
            # Never pull an out-of-scope parent into the usable graph.
            return None
        return self._repo.upsert_asset(
            parent.canonical_key,
            parent.asset_type,
            display_value=parent.canonical_key,
            scope_id=scope_id,
            metadata={"origin": "parent_link", "discovered_by": source.strip()},
        )
