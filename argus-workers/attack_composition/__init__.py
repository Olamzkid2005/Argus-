"""
Attack composition package — planning logic extracted from attack_graph.py.

This package contains the planning/phase-generation components that were
originally part of AttackGraph. The graph data structures remain in
attack_graph.py.

Backward-compatible re-exports allow existing code to import from
attack_composition.planner directly while the old attack_graph imports
continue to work via the re-exports in __init__.py (which import from
attack_graph and re-export only the moved symbols).

Usage:
    from attack_composition import generate_plan_from_graph
    from attack_composition.planner import generate_plan_from_graph, CHAIN_TO_CAPABILITIES
"""

from attack_composition.planner import CHAIN_TO_CAPABILITIES, generate_plan_from_graph

__all__ = [
    "generate_plan_from_graph",
    "CHAIN_TO_CAPABILITIES",
]
