"""Generate human-readable narratives for attack paths."""

from __future__ import annotations


def generate_narrative(path_info: dict, findings: list[dict]) -> str:
    """Generate a narrative description of an attack path."""
    path = path_info.get("path", [])
    score = path_info.get("score", 0)
    steps = path_info.get("steps", 0)

    if not path:
        return "No attack path to describe."

    severity_label = "critical" if score > 10 else "high" if score > 6 else "medium" if score > 3 else "low"

    narrative_parts = [
        f"This {severity_label}-severity attack path ({steps} steps, risk score: {score}) "
        f"allows an attacker to progress from initial access to compromise.",
    ]

    for i, node in enumerate(path):
        label = node.replace("host:", "").replace("page:", "/")
        if i == 0:
            narrative_parts.append(f"Starting point: {label}")
        elif i == len(path) - 1:
            narrative_parts.append(f"Crown jewel access: {label}")
        else:
            narrative_parts.append(f"Step {i}: {label}")

    narrative_parts.append(
        "Recommendation: Address the earliest finding in this chain to break the attack path."
    )

    return "\n\n".join(narrative_parts)
