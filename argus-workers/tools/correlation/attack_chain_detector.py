"""Detect attack chains — sequences of findings that combine into exploits."""

from __future__ import annotations

from collections import defaultdict


def _endpoint_host(endpoint: str) -> str:
    from urllib.parse import urlparse

    try:
        return urlparse(endpoint).hostname or endpoint
    except Exception:
        return endpoint


def _build_dependency_graph(findings: list[dict]) -> dict[str, list[str]]:
    """Build a graph of finding dependencies based on endpoint and type relationships."""
    graph: dict[str, list[str]] = defaultdict(list)

    by_host: dict[str, list[int]] = defaultdict(list)
    for i, f in enumerate(findings):
        host = _endpoint_host(f.get("endpoint", ""))
        by_host[host].append(i)

    TYPE_PRECEDENCE = {
        "SUBDOMAIN_TAKEOVER": ["JWT_EXPOSURE", "SECRET_EXPOSURE"],
        "RECON": ["VULNERABILITY", "SECRET_EXPOSURE"],
        "XSS": ["CSRF", "SESSION_HIJACK", "PRIVILEGE_ESCALATION"],
        "SQL_INJECTION": ["DATA_EXFILTRATION", "PRIVILEGE_ESCALATION"],
        "SSRF": ["INTERNAL_ACCESS", "DATA_EXFILTRATION"],
        "WEAK_AUTHENTICATION": ["PRIVILEGE_ESCALATION", "SESSION_HIJACK"],
        "MISCONFIGURATION": ["INFORMATION_DISCLOSURE", "UNAUTHORIZED_ACCESS"],
    }
    for _host, indices in by_host.items():
        types_at_host: dict[str, list[int]] = {}
        for idx in indices:
            ftype = findings[idx].get("type", "UNKNOWN")
            types_at_host.setdefault(ftype, []).append(idx)

        for ftype, source_indices in types_at_host.items():
            for target_type in TYPE_PRECEDENCE.get(ftype, []):
                for target_idx in types_at_host.get(target_type, []):
                    for si in source_indices:
                        graph[str(si)].append(str(target_idx))

    return dict(graph)


def _detect_chains(graph: dict[str, list[str]], findings: list[dict]) -> list[dict]:
    """Find longest paths in the dependency graph (attack chains)."""
    visited: set[str] = set()
    chains: list[dict] = []

    def _dfs(node: str, path: list[str]) -> None:
        if node in visited:
            if len(path) > 1:
                chains.append(_build_chain(path, findings))
            return
        visited.add(node)
        path.append(node)
        for neighbor in graph.get(node, []):
            _dfs(neighbor, path)
        if len(path) > 1 and not graph.get(node):
            chains.append(_build_chain(path, findings))
        path.pop()
        visited.discard(node)

    for node in graph:
        if node not in visited:
            _dfs(node, [])

    chains.sort(key=lambda c: len(c.get("steps", [])), reverse=True)
    return chains


def _build_chain(path: list[str], findings: list[dict]) -> dict:
    steps = []
    for idx_str in path:
        idx = int(idx_str)
        f = findings[idx]
        steps.append(
            {
                "finding_id": f.get("id", f.get("type", "")),
                "type": f.get("type", "UNKNOWN"),
                "severity": f.get("severity", "INFO"),
                "endpoint": f.get("endpoint", ""),
            }
        )

    severities = [s["severity"] for s in steps]
    max_sev = max(
        severities,
        key=lambda s: {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0}.get(
            s, 0
        ),
    )

    return {
        "chain_length": len(steps),
        "max_severity": max_sev,
        "steps": steps,
        "description": " → ".join(s["type"] for s in steps),
    }


def detect_attack_chains(findings: list[dict], max_chains: int = 10) -> list[dict]:
    """Detect attack chains from a list of findings.

    Returns up to max_chains attack chains sorted by length and severity.
    """
    if len(findings) < 2:
        return []

    graph = _build_dependency_graph(findings)
    if not graph:
        return []

    chains = _detect_chains(graph, findings)
    return chains[:max_chains]
