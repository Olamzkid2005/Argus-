"""Render attack paths as text narratives."""

from __future__ import annotations


def render_text_path(path_info: dict) -> str:
    """Render a single attack path as a readable text narrative."""
    path = path_info.get("path", [])
    score = path_info.get("score", 0)
    steps = path_info.get("steps", 0)

    lines = [f"Attack Path ({steps} steps, score: {score}):"]

    for i, node in enumerate(path):
        prefix = "  " + ("→ " if i > 0 else "  ")
        label = node.replace("host:", "").replace("page:", "/")
        lines.append(f"{prefix}{label}")

    return "\n".join(lines)


def render_all_paths(ranked_paths: list[dict]) -> str:
    """Render all ranked attack paths as text."""
    if not ranked_paths:
        return "No attack paths detected."

    sections = [f"Found {len(ranked_paths)} attack path(s):\n"]
    for i, rp in enumerate(ranked_paths, 1):
        sections.append(f"Path {i}:")
        sections.append(render_text_path(rp))
        sections.append("")

    return "\n".join(sections)


def render_mermaid(ranked_paths: list[dict]) -> str:
    """Render attack paths as a Mermaid diagram."""
    lines = ["graph TD"]
    node_map: dict[str, str] = {}
    counter = 0

    for rp in ranked_paths[:5]:
        path = rp.get("path", [])
        for i in range(len(path) - 1):
            src = path[i]
            dst = path[i + 1]

            if src not in node_map:
                counter += 1
                node_map[src] = f"N{counter}"
                label = src.replace("host:", "")
                lines.append(f"    {node_map[src]}[\"{label}\"]")

            if dst not in node_map:
                counter += 1
                node_map[dst] = f"N{counter}"
                label = dst.replace("host:", "")
                lines.append(f"    {node_map[dst]}[\"{label}\"]")

            lines.append(f"    {node_map[src]} --> {node_map[dst]}")

    return "\n".join(lines)
