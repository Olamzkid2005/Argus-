"""Workflows Package — Step-based workflow primitives for BOLA/BOPLA and future variants.

Provides:
- WorkflowStep: Abstract base class for all workflow steps
- WorkflowContext: Per-execution state shared across steps
- StepResult: Per-step return value
- WorkflowResult: Uniform return type for all workflow classes
- Workflow: Abstract base class for future workflow types (V2+)
- BolaWorkflow: Concrete BOLA/BOPLA workflow (V1)
"""

from .base import StepResult, Workflow, WorkflowContext, WorkflowResult, WorkflowStep
from .bola import BolaWorkflow

__all__ = [
    "BolaWorkflow",
    "StepResult",
    "Workflow",
    "WorkflowContext",
    "WorkflowResult",
    "WorkflowStep",
]
