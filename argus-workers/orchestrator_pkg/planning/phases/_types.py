"""Shared types for phase modules — avoids circular imports with adaptive_planner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Convenience type aliases for ReconContext-like objects
_ReconCtx = Any
_ActivationResult = tuple[bool, str]


@dataclass
class ToolTask:
    """A single tool execution within a testing phase.

    Attributes:
        tool_name: Name of the tool to run (must be registered in tool_definitions).
        description: Human-readable purpose of this tool execution.
        priority: Execution order within the phase (lower = earlier). Default 100.
        timeout: Max execution time in seconds. Default 180.
        args_template: Tool argument list with placeholder strings like ``{target}``,
                       ``{targets}``, ``{engagement_id}`` that get resolved at runtime.
        required: If True, phase failure marks this task as critical. Default False.
    """
    tool_name: str
    description: str = ""
    priority: int = 100
    timeout: int = 180
    args_template: list[str] = field(default_factory=list)
    required: bool = False


def _has_min_recon(recon_context) -> bool:
    """Check if ReconContext is non-None and has basic data."""
    return recon_context is not None


def _get_tech_stack(recon_context) -> list[str]:
    """Safely extract tech_stack from ReconContext."""
    if recon_context and hasattr(recon_context, "tech_stack"):
        return recon_context.tech_stack or []
    return []


def _get_attr(recon_context, name: str, default=None):
    """Safely get an attribute from ReconContext."""
    if recon_context and hasattr(recon_context, name):
        return getattr(recon_context, name, default)
    return default


__all__ = [
    "ToolTask",
    "_ReconCtx",
    "_ActivationResult",
    "_has_min_recon",
    "_get_tech_stack",
    "_get_attr",
]
