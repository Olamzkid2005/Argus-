"""Build an attack graph from findings, assets, and roles."""

from __future__ import annotations

from collections import defaultdict


def build_asset_graph(findings: list[dict]) -> dict[str, list[dict]]:
    """Build a graph of assets and their relationships from findings.

    Returns dict mapping asset_id → list of connected assets.
    """
    graph: dict[str, list[dict]] = defaultdict(list)

    for f in findings:
        endpoint = f.get("endpoint", "")
        ftype = f.get("type", "UNKNOWN")
        severity = f.get("severity", "INFO")

        from urllib.parse import urlparse

        try:
            parsed = urlparse(endpoint)
            host = parsed.hostname or endpoint
            path = parsed.path or "/"
        except Exception:
            host = endpoint
            path = "/"

        asset_id = f"host:{host}"
        graph[asset_id].append(
            {
                "type": "host",
                "value": host,
                "finding_type": ftype,
                "severity": severity,
            }
        )

        if path and path != "/":
            page_id = f"page:{host}{path}"
            graph[page_id].append(
                {
                    "type": "page",
                    "value": f"{host}{path}",
                    "finding_type": ftype,
                    "severity": severity,
                }
            )
            graph[asset_id].append(
                {
                    "type": "contains",
                    "target": page_id,
                    "finding_type": ftype,
                    "severity": severity,
                }
            )

    return dict(graph)


ENTRY_TYPES = {
    "RECON",
    "SUBDOMAIN_TAKEOVER",
    "OPEN_REDIRECT",
    "INFORMATION_DISCLOSURE",
    "MISCONFIGURATION",
    "WEAK_AUTHENTICATION",
}

CROWN_JEWEL_TYPES = {
    "DATA_EXFILTRATION",
    "SQL_INJECTION",
    "COMMAND_INJECTION",
    "RCE",
    "PRIVILEGE_ESCALATION",
    "AUTH_BYPASS",
}
