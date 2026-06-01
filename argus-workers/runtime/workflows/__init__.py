"""Workflows Package — Step-based workflow primitives for BOLA/BOPLA and future variants.

Provides:
- WorkflowStep: Abstract base class for all workflow steps
- WorkflowContext: Per-execution state shared across steps
- StepResult: Per-step return value
- WorkflowResult: Uniform return type for all workflow classes
- Workflow: Abstract base class for future workflow types (V2+)
"""

from .base import StepResult, Workflow, WorkflowContext, WorkflowResult, WorkflowStep

__all__ = [
    "StepResult",
    "Workflow",
    "WorkflowContext",
    "WorkflowResult",
    "WorkflowStep",
]
