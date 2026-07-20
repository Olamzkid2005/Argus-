"""
Adaptive Workflow Planner — dynamically chains testing phases based on recon signals.

The planner analyzes ReconContext signals to produce an ordered, dependency-aware
testing plan. Each phase activates only when relevant signals are present, and
results from early phases can trigger follow-up phases.

Usage:
    from orchestrator_pkg.planning import AdaptiveWorkflowPlanner, WorkflowPlan

    planner = AdaptiveWorkflowPlanner()
    plan = planner.build_plan(recon_context, engagement_id="eng-123")
    for phase in plan.phases:
        print(f"{phase.name}: {len(phase.tools)} tool(s)")
"""

from .adaptive_planner import (
    AdaptiveWorkflowPlanner,
    TestingPhase,
    ToolTask,
    WorkflowPlan,
)

__all__ = [
    "AdaptiveWorkflowPlanner",
    "ToolTask",
    "TestingPhase",
    "WorkflowPlan",
]
