"""
Recon -> ARTEX asset graph ingestion bridge (A2).

Recon already produces a structured ``ReconContext`` (live endpoints, subdomains,
open ports, crawled/API/auth URLs). This module feeds those outcomes into the
canonical asset graph through ``DispatcherGraph.ingest_observation`` so real tool
results create observations and assets instead of the graph only ever being
populated by tests.

Ingestion is deliberately best-effort: a malformed or out-of-scope observation is
counted and skipped, never raised into the recon task. The graph is additive and
must not abort a scan.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

from database.dispatcher_graph import DispatcherGraph
from database.graph_repository import ExplorationGraphRepository

logger = logging.getLogger(__name__)

# Bounds a single recon pass; recon contexts are already capped per field, this
# guards against a caller passing a huge ad-hoc context.
_MAX_ASSETS_PER_RUN = 500

_ENDPOINT_FIELDS = (
    "live_endpoints",
    "crawled_paths",
    "api_endpoints",
    "auth_endpoints",
    "parameter_bearing_urls",
    "ai_endpoints",
)

_UNSET = object()


def _field(context: Any, name: str, default: Any) -> Any:
    if isinstance(context, dict):
        return context.get(name, default) or default
    return getattr(context, name, default) or default


def _target_host(target_url: str) -> str | None:
    if not target_url:
        return None
    try:
        return urlsplit(target_url).hostname
    except ValueError:
        return None


def _service_identity(host: str, entry: dict) -> str | None:
    port = entry.get("port")
    if not isinstance(port, int) or not 0 < port <= 65535:
        return None
    protocol = str(entry.get("protocol") or "tcp").strip().lower() or "tcp"
    bracketed = f"[{host}]" if ":" in host else host
    return f"{bracketed}:{port}/{protocol}"


def load_engagement_scope(engagement_id: str) -> dict | str | None:
    """
    Read the engagement's ``authorized_scope`` column (migration 022).

    Returns None when the row or column is missing: ingestion then has no scope
    to enforce, matching how the graph treats an unscoped engagement.
    """
    try:
        from database.connection import db_cursor

        with db_cursor() as cursor:
            cursor.execute(
                "SELECT authorized_scope FROM engagements WHERE id = %s",
                (engagement_id,),
            )
            row = cursor.fetchone()
            return row[0] if row else None
    except Exception as exc:  # noqa: BLE001 - scope lookup must not break recon
        logger.warning(
            "Could not load authorized_scope for engagement %s: %s", engagement_id, exc
        )
        return None


def _candidates(context: Any) -> list[tuple[str, str]]:
    """Flatten a recon context into (asset_type, observed_value) pairs."""
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(asset_type: str, value: Any) -> None:
        if not isinstance(value, str):
            return
        value = value.strip()
        if not value:
            return
        key = (asset_type, value)
        if key in seen:
            return
        seen.add(key)
        pairs.append(key)

    target_url = _field(context, "target_url", "")
    if isinstance(target_url, str):
        add("endpoint", target_url)

    for field_name in _ENDPOINT_FIELDS:
        for value in _field(context, field_name, []):
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                add("endpoint", value)

    for subdomain in _field(context, "subdomains", []):
        add("subdomain", subdomain)

    host = _target_host(target_url if isinstance(target_url, str) else "")
    if host:
        for entry in _field(context, "open_ports", []):
            if not isinstance(entry, dict):
                continue
            identity = _service_identity(host, entry)
            if identity:
                add("service", identity)

    return pairs


def ingest_recon_outcomes(
    engagement_id: str,
    recon_context: Any,
    *,
    authorized_scope: dict | str | None = _UNSET,
    source: str = "recon",
    repository: ExplorationGraphRepository | None = None,
    max_assets: int = _MAX_ASSETS_PER_RUN,
) -> dict[str, Any]:
    """
    Ingest one recon context into the canonical asset graph.

    Returns counts plus a compact sample of what was ingested; never raises for a
    single bad observation.
    """
    if recon_context is None:
        return {
            "status": "skipped",
            "reason": "no_recon_context",
            "accepted": 0,
            "rejected": 0,
            "failed": 0,
            "assets": [],
        }

    if authorized_scope is _UNSET:
        authorized_scope = load_engagement_scope(engagement_id)

    dispatcher = DispatcherGraph(repository or ExplorationGraphRepository())
    accepted = 0
    rejected = 0
    failed = 0
    assets: list[dict[str, Any]] = []

    for asset_type, observed_value in _candidates(recon_context)[:max_assets]:
        try:
            outcome = dispatcher.ingest_observation(
                asset_type,
                observed_value,
                source=source,
                scope_id=engagement_id,
                authorized_scope=authorized_scope,
            )
        except Exception as exc:  # noqa: BLE001 - one bad value must not abort recon
            failed += 1
            logger.debug(
                "Graph ingestion skipped %s %r: %s", asset_type, observed_value, exc
            )
            continue

        if outcome["accepted"]:
            accepted += 1
            assets.append(
                {
                    "id": outcome["asset"]["id"],
                    "type": asset_type,
                    "canonical_key": outcome["canonical_key"],
                }
            )
        else:
            rejected += 1

    logger.info(
        "Graph ingestion for engagement %s: %d accepted, %d rejected, %d failed",
        engagement_id,
        accepted,
        rejected,
        failed,
    )
    return {
        "status": "completed",
        "accepted": accepted,
        "rejected": rejected,
        "failed": failed,
        "assets": assets,
    }


def ingest_recon_result(
    engagement_id: str,
    recon_result: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    """Ingest the ``recon_context`` of an orchestrator recon result, best-effort."""
    if not isinstance(recon_result, dict):
        return {"status": "skipped", "reason": "no_recon_result", "accepted": 0}
    context = recon_result.get("recon_context")
    if not context:
        return {"status": "skipped", "reason": "no_recon_context", "accepted": 0}
    try:
        return ingest_recon_outcomes(engagement_id, context, **kwargs)
    except Exception as exc:  # noqa: BLE001 - graph ingestion is never fatal
        logger.warning(
            "Graph ingestion from recon failed for engagement %s: %s",
            engagement_id,
            exc,
        )
        return {"status": "failed", "error": str(exc), "accepted": 0}
