"""
Attack planner — generates exploitation phase plans from attack chains.

Extracted from attack_graph.py to separate planning concerns from graph
data structures. Takes AttackGraph as an explicit parameter rather than
being a method on the graph class.

This module is the single source of truth for chain-to-capability mapping
and exploitation phase planning.
"""

from typing import Any

from attack_graph import AttackGraph, Path


# Map chain IDs to suggested capabilities for exploitation
CHAIN_TO_CAPABILITIES: dict[str, list[str]] = {
    "chain_1": ["open_redirect", "auth"],
    "chain_2": ["xss", "csrf"],
    "chain_3": ["cloud_metadata_probe", "post_exploitation"],
    "chain_4": ["lfi", "command_injection"],
    "chain_5": ["subdomain_takeover", "cors"],
    "chain_6": ["xss", "session_hijack_attempt"],
    "chain_7": ["idor", "privilege_escalation"],
    "chain_8": ["open_redirect", "phishing_chain"],
}


def generate_plan_from_graph(graph: AttackGraph) -> list[dict[str, Any]]:
    """
    Generate an ordered list of exploitation phases from detected attack chains.

    Each detected chain is converted into a phase plan that the TypeScript
    planner can insert into the workflow. Chains with higher risk scores
    and CRITICAL severity are prioritized.

    Args:
        graph: AttackGraph instance with findings already added

    Returns:
        List of phase plan dicts, each with:
        - chain_id: str — matches CHAIN_RULES[].id
        - name: str — human-readable chain name
        - severity: str — overall chain severity
        - risk_score: float — computed risk score
        - prerequisite_finding_types: list[str] — finding types that triggered this chain
        - suggested_capabilities: list[str] — what capabilities to run next
        - description: str — chain description
    """
    chains = graph.find_chains()
    if not chains:
        return []

    # Collect unique chain results
    seen = set()
    plans: list[dict[str, Any]] = []
    for chain in chains:
        chain_id = chain.get("chain_id", "")
        if chain_id in seen:
            continue
        seen.add(chain_id)

        prereq_node = chain.get("prereq_node")
        chain_node = chain.get("chain_node")
        prereq_type = str(prereq_node.data.get("type", "")) if prereq_node else ""
        chain_type = str(chain_node.data.get("type", "")) if chain_node else ""

        # Compute risk score from the chain path
        path = (
            Path(nodes=[prereq_node, chain_node], edges=[])
            if prereq_node and chain_node
            else None
        )
        risk_score = graph.compute_risk(path) if path else 0.0

        plans.append(
            {
                "chain_id": chain_id,
                "name": chain.get("name", "Unknown chain"),
                "severity": chain.get("severity", "MEDIUM"),
                "risk_score": round(risk_score, 2),
                "prerequisite_finding_types": [prereq_type, chain_type],
                "suggested_capabilities": CHAIN_TO_CAPABILITIES.get(chain_id, []),
                "description": chain.get("description", ""),
            }
        )

    # Sort by severity (CRITICAL first) then risk score descending
    severity_order = {
        "CRITICAL": 0,
        "HIGH": 1,
        "MEDIUM": 2,
        "LOW": 3,
        "INFO": 4,
    }
    plans.sort(
        key=lambda p: (severity_order.get(p["severity"], 5), -p["risk_score"])
    )

    return plans
