"""Find attack paths in the asset graph using BFS."""

from __future__ import annotations

from collections import defaultdict, deque


def find_paths(
    graph: dict[str, list[dict]],
    findings: list[dict],
    max_paths: int = 10,
    max_depth: int = 8,
) -> list[list[str]]:
    """Find paths from entry points to crown jewels using BFS.

    Returns list of paths, each path is a list of node IDs.
    """
    entry_nodes: list[str] = []
    crown_jewel_nodes: list[str] = []

    for f in findings:
        endpoint = f.get("endpoint", "")
        ftype = (f.get("type", "") or "").upper().replace(" ", "_").replace("-", "_")

        from urllib.parse import urlparse
        try:
            host = urlparse(endpoint).hostname or endpoint
        except Exception:
            host = endpoint

        node_id = f"host:{host}"

        ENTRY_TYPES = {"RECON", "SUBDOMAIN_TAKEOVER", "OPEN_REDIRECT", "INFORMATION_DISCLOSURE", "MISCONFIGURATION", "WEAK_AUTHENTICATION"}
        CROWN_JEWEL_TYPES = {"DATA_EXFILTRATION", "SQL_INJECTION", "COMMAND_INJECTION", "RCE", "PRIVILEGE_ESCALATION", "AUTH_BYPASS"}

        if ftype in ENTRY_TYPES and node_id not in entry_nodes:
            entry_nodes.append(node_id)
        if ftype in CROWN_JEWEL_TYPES and node_id not in crown_jewel_nodes:
            crown_jewel_nodes.append(node_id)

    if not entry_nodes or not crown_jewel_nodes:
        return []

    adj: dict[str, list[str]] = defaultdict(list)
    for node_id, edges in graph.items():
        for edge in edges:
            target = edge.get("target")
            if target:
                adj[node_id].append(target)
            elif edge.get("type") == "contains":
                adj[node_id].append(edge.get("target", ""))

    paths: list[list[str]] = []
    for entry in entry_nodes:
        for crown in crown_jewel_nodes:
            if entry == crown:
                paths.append([entry])
                continue

            visited: set[str] = {entry}
            queue: deque[tuple[str, list[str]]] = deque([(entry, [entry])])

            while queue and len(paths) < max_paths:
                current, path = queue.popleft()
                if len(path) > max_depth:
                    continue

                for neighbor in adj.get(current, []):
                    if neighbor in visited:
                        continue
                    new_path = path + [neighbor]
                    if neighbor == crown:
                        paths.append(new_path)
                    else:
                        visited.add(neighbor)
                        queue.append((neighbor, new_path))

    paths.sort(key=len)
    return paths[:max_paths]
