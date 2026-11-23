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

import ipaddress
import logging
from typing import Any
from urllib.parse import urlsplit

from database.dispatcher_graph import DispatcherGraph
from database.graph_repository import ExplorationGraphRepository, load_authorized_scope

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


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


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
        # A target that is itself an IP proves the approved ip_range was reached.
        if _is_ip(host):
            add("ip", host)
        for entry in _field(context, "open_ports", []):
            if not isinstance(entry, dict):
                continue
            entry_host = entry.get("host") or entry.get("ip")
            if isinstance(entry_host, str) and _is_ip(entry_host.strip()):
                add("ip", entry_host.strip())
            identity = _service_identity(host, entry)
            if identity:
                add("service", identity)

    # Recon runners that expand an approved CIDR report the reached addresses
    # here; without this an ip_range gap could never be proven discovered.
    for value in _field(context, "ips", []):
        if isinstance(value, str) and _is_ip(value.strip()):
            add("ip", value.strip())

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
        authorized_scope = load_authorized_scope(engagement_id)

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

    # Gaps the recon pass leaves behind become scheduled work, not just report
    # lines: approved-but-undiscovered targets and untested asset classes get a
    # planner frontier node plus todo. Best-effort like ingestion itself.
    scheduled_gaps = 0
    try:
        scheduled_gaps = dispatcher.schedule_coverage_gaps(
            engagement_id, engagement_id, authorized_scope=authorized_scope
        )["scheduled_count"]
    except Exception as exc:  # noqa: BLE001 - planning must not abort recon
        logger.debug(
            "Coverage gap scheduling skipped for engagement %s: %s",
            engagement_id,
            exc,
        )

    logger.info(
        "Graph ingestion for engagement %s: %d accepted, %d rejected, %d failed, "
        "%d coverage gap(s) scheduled",
        engagement_id,
        accepted,
        rejected,
        failed,
        scheduled_gaps,
    )
    return {
        "status": "completed",
        "accepted": accepted,
        "rejected": rejected,
        "failed": failed,
        "scheduled_gaps": scheduled_gaps,
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
