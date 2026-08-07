"""
AdaptiveWorkflowPlanner — dynamically generates an ordered testing plan from recon signals.

Design
------

Instead of running a fixed sequence of phases (recon → scan → analyze → report),
the planner examines ReconContext signals and produces a **WorkflowPlan** with
ordered TestingPhases. Each phase activates only when its preconditions are met:

    has_login_page=True  ──►  auth_testing phase
    +                            │
    auth_endpoints found ────────┤
                                 ▼
                          session_analysis phase
                                 │
                                 ▼
                          access_control phase

The planner is **signal-driven, not tool-driven**: phases define *what to test*
(authentication, authorization, API security, etc.), not *which binary to run*.
Tool selection within each phase is a separate concern.

Integration
-----------

The orchestrator calls the planner after recon completes (ReconContext is available).
The resulting WorkflowPlan:
  1. Guides the LLM agent's tool selection (agent receives phase descriptions)
  2. Configures the deterministic safety-net (skips irrelevant phases, focuses on active ones)
  3. Provides observability (logs which phases were activated and why)

Extending
---------

Add new phases by appending to PHASE_DEFINITIONS. Each definition requires:
  - A descriptive name
  - An activation function (receives ReconContext → bool)
  - An ordered list of tool tasks with priority, timeout, and args template
  - An optional list of follow-up phases to trigger if results are found
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from orchestrator_pkg.planning.phases import _PhaseDefinition
from orchestrator_pkg.planning.phases._types import (
    ToolTask,
    _get_attr,
    _has_min_recon,
)

logger = logging.getLogger(__name__)


# ── Data Structures ────────────────────────────────────────────────────


@dataclass
class TestingPhase:
    # Tell pytest this is NOT a test class (prevents PytestCollectionWarning
    # from dataclass-generated __init__ interfering with test discovery)
    __test__ = False

    """A logical testing objective, e.g. "authentication testing".

    Attributes:
        name: Short unique identifier (e.g. ``auth_testing``).
        description: Human-readable phase description.
        activation_reason: Why this phase was activated (populated at plan time).
        order: Execution sequence across all phases (lower = earlier).
        tools: Ordered list of ToolTask instances to execute.
        triggers: Phase names to consider activating if this phase produces findings.
        depends_on: Phase names that should execute before this one.
    """

    name: str
    description: str = ""
    activation_reason: str = ""
    order: int = 100
    tools: list[ToolTask] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)


@dataclass
class WorkflowPlan:
    """An ordered testing plan generated from ReconContext signals.

    Attributes:
        phases: Ordered list of TestingPhase instances to execute.
        summary: One-line description of the plan.
        target_url: The target being tested.
        total_phases: Number of phases in the plan.
        activated_phases: Number of phases that were activated (vs. skipped).
        skipped_phases: Phase names that were evaluated but not activated, with reasons.
    """

    phases: list[TestingPhase] = field(default_factory=list)
    summary: str = ""
    target_url: str = ""
    total_phases: int = 0
    activated_phases: int = 0
    skipped_phases: list[dict[str, str]] = field(default_factory=list)

    def get_coverage_report(self) -> dict:
        """Return a structured coverage report comparing planned vs executed phases.

        Shows which phases were activated, which were skipped (with reasons),
        and what percentage of the potential attack surface was covered.

        Returns:
            Dict with coverage_gaps (list of skipped phases), activated (list of
            active phases), activated_count, skipped_count, total_phases, and
            coverage_pct (float 0.0-1.0).
        """
        if not self.phases and not self.skipped_phases:
            return {
                "coverage_gaps": [],
                "activated": [],
                "activated_count": 0,
                "skipped_count": 0,
                "total_phases": self.total_phases,
                "coverage_pct": 0.0,
                "summary": self.summary,
            }
        activated_names = [p.name for p in self.phases]
        skipped_info = [
            {"name": s.get("name", "unknown"), "reason": s.get("reason", "")}
            for s in self.skipped_phases
        ]
        evaluable = self.total_phases or (len(self.phases) + len(self.skipped_phases))
        coverage_pct = self.activated_phases / max(evaluable, 1)
        return {
            "coverage_gaps": skipped_info,
            "activated": activated_names,
            "activated_count": self.activated_phases,
            "skipped_count": len(self.skipped_phases),
            "total_phases": evaluable,
            "coverage_pct": round(coverage_pct, 3),
            "summary": self.summary,
        }


# ── Phase Registry (imported from planning/phases/) ──
from orchestrator_pkg.planning.phases import PHASE_DEFINITIONS  # noqa: E402, F401

# ── Planner ────────────────────────────────────────────────────────────


class AdaptiveWorkflowPlanner:
    """Generates an ordered, signal-driven testing plan from ReconContext.

    The planner evaluates each phase definition against the recon signals,
    resolves inter-phase dependencies, and produces a WorkflowPlan with
    phases ordered for logical execution.

    Usage::

        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(recon_context, engagement_id="eng-123")
        for phase in plan.phases:
            print(f"{phase.activation_reason}")
            for task in phase.tools:
                print(f"  -> {task.tool_name}")
    """

    def __init__(self, phase_definitions: list[_PhaseDefinition] | None = None):
        """Initialize the planner with an optional custom phase registry.

        Args:
            phase_definitions: Custom phase definitions. Defaults to PHASE_DEFINITIONS.
        """
        self.phase_defs = phase_definitions or PHASE_DEFINITIONS
        self._last_recon_context: Any = {}  # Updated to actual context on build_plan()

    def build_plan(
        self,
        recon_context: Any,
        engagement_id: str = "",
    ) -> WorkflowPlan:
        """Build a WorkflowPlan from ReconContext signals.

        Evaluates each phase definition, activates those whose preconditions
        are met, resolves inter-phase dependencies, and returns an ordered plan.

        Args:
            recon_context: ReconContext instance from the recon phase.
            engagement_id: Optional engagement ID for logging.

        Returns:
            WorkflowPlan with ordered, activated phases.
        """
        target_url = _get_attr(recon_context, "target_url", "")

        if not _has_min_recon(recon_context):
            logger.info(
                "[AdaptivePlanner] No recon context — returning empty plan "
                "(engagement=%s)",
                engagement_id,
            )
            return WorkflowPlan(
                summary="No recon context available — skipping adaptive planning",
                target_url=target_url,
            )

        self._last_recon_context = recon_context

        # ── Step 1: Evaluate all phase definitions ──
        activated: list[TestingPhase] = []
        skipped: list[dict[str, str]] = []
        all_names: set[str] = {p.name for p in self.phase_defs}

        for phase_def in self.phase_defs:
            should_activate, reason = phase_def.activate_fn(recon_context)
            if should_activate:
                tools = phase_def.tools_fn(recon_context)
                # Resolve triggers — only keep triggers that are valid phase names
                valid_triggers = [t for t in phase_def.triggers if t in all_names]
                # Resolve depends_on — only keep valid phase names
                valid_deps = [d for d in phase_def.depends_on if d in all_names]
                phase = TestingPhase(
                    name=phase_def.name,
                    description=phase_def.description,
                    activation_reason=reason,
                    order=phase_def.order,
                    tools=tools,
                    triggers=valid_triggers,
                    depends_on=valid_deps,
                )
                activated.append(phase)
                logger.info(
                    "[AdaptivePlanner] Activated phase '%s' (%s) — %s "
                    "(engagement=%s)",
                    phase_def.name,
                    phase_def.description,
                    reason,
                    engagement_id,
                )
            else:
                skipped.append({"phase": phase_def.name, "reason": reason})
                logger.debug(
                    "[AdaptivePlanner] Skipped phase '%s': %s (engagement=%s)",
                    phase_def.name,
                    reason,
                    engagement_id,
                )

        # ── Step 2: Resolve depends_on — reorder so dependencies come first ──
        ordered = self._order_phases(activated)

        # ── Step 3: Build summary ──
        total_phases = len(self.phase_defs)
        activated_names = [p.name for p in ordered]
        summary_parts = [f"phases: {', '.join(activated_names)}"] if ordered else ["no phases activated"]

        plan = WorkflowPlan(
            phases=ordered,
            summary="; ".join(summary_parts),
            target_url=target_url,
            total_phases=total_phases,
            activated_phases=len(ordered),
            skipped_phases=skipped,
        )

        logger.info(
            "[AdaptivePlanner] Plan complete: %d/%d phases activated "
            "(engagement=%s, target=%s)",
            len(ordered),
            total_phases,
            engagement_id,
            target_url,
        )
        return plan

    @staticmethod
    def _order_phases(phases: list[TestingPhase]) -> list[TestingPhase]:
        """Order phases respecting dependencies, using a simple topological sort.

        Args:
            phases: List of activated phases (potentially unsorted).

        Returns:
            Phases ordered so that dependencies come before dependents,
            and phases with lower order numbers come first within the same
            dependency level.
        """
        if not phases:
            return []

        # Build dependency graph
        phase_map = {p.name: p for p in phases}
        name_set = set(phase_map.keys())

        # Topological sort (Kahn's algorithm)
        in_degree: dict[str, int] = {p.name: 0 for p in phases}
        dependents: dict[str, list[str]] = {p.name: [] for p in phases}

        for p in phases:
            for dep in p.depends_on:
                if dep in name_set:
                    in_degree[p.name] = in_degree.get(p.name, 0) + 1
                    if dep not in dependents:
                        dependents[dep] = []
                    dependents[dep].append(p.name)

        # Start with phases that have no unmet dependencies, sorted by order
        ready = sorted(
            [p for p in phases if in_degree.get(p.name, 0) == 0],
            key=lambda p: p.order,
        )

        ordered: list[TestingPhase] = []
        while ready:
            current = ready.pop(0)
            ordered.append(current)
            for dep_name in dependents.get(current.name, []):
                in_degree[dep_name] -= 1
                if in_degree[dep_name] == 0:
                    dep_phase = phase_map.get(dep_name)
                    if dep_phase:
                        # Insert in sorted position by order
                        ready.append(dep_phase)
                        ready.sort(key=lambda p: p.order)

        # Add any remaining phases that weren't ordered (cycles or missing deps)
        remaining = [p for p in phases if p not in ordered]
        ordered.extend(sorted(remaining, key=lambda p: p.order))

        return ordered

    def format_plan_for_agent(self, plan: WorkflowPlan) -> str:
        """Format the plan as a compact text block for LLM agent consumption.

        The formatted plan is injected into the agent's system prompt so the
        LLM knows which testing phases are recommended and why.

        Args:
            plan: The WorkflowPlan to format.

        Returns:
            Compact multi-line string suitable for inclusion in an LLM prompt.
        """
        if not plan or not plan.phases:
            return ""

        lines = [
            "=== ADAPTIVE TESTING PLAN ===",
            f"Target: {plan.target_url}",
            f"Phases: {plan.activated_phases}/{plan.total_phases} activated",
            "",
        ]
        for i, phase in enumerate(plan.phases, 1):
            lines.append(f"  Phase {i}: {phase.name}")
            lines.append(f"    {phase.description}")
            lines.append(f"    Reason: {phase.activation_reason}")
            for task in phase.tools:
                lines.append(f"    Tool: {task.tool_name} — {task.description}")
            if phase.triggers:
                lines.append(f"    Follow-up: {', '.join(phase.triggers)}")
            lines.append("")
        lines.append("=== END TESTING PLAN ===")
        return "\n".join(lines)

    @staticmethod
    def resolve_tool_args(
        task: ToolTask,
        target: str,
        engagement_id: str = "",
    ) -> list[str]:
        """Resolve placeholder strings in a ToolTask's args_template.

        Supported placeholders:
          - ``{target}`` — the target URL
          - ``{targets}`` — comma-separated targets (same as target for single-target)
          - ``{engagement_id}`` — the engagement UUID

        Args:
            task: The ToolTask whose args_template to resolve.
            target: The target URL to substitute.
            engagement_id: The engagement ID to substitute.

        Returns:
            Resolved argument list ready for tool execution.
        """
        return [
            arg.replace("{target}", target)
               .replace("{targets}", target)
               .replace("{engagement_id}", engagement_id)
            for arg in task.args_template
        ]

    def should_continue(
        self,
        plan: WorkflowPlan,
        phase_results: list[dict],
        hypotheses: list[dict] | None = None,
        budget_remaining: dict | None = None,
    ) -> bool:
        """Determine whether the assessment should continue to the next phase.

        Called after each phase completes. Returns False if:
        - The current phase produced zero findings (fruitless path)
        - Budget is exhausted (time or phase limit reached)
        - All planned phases have been executed

        Returns True if:
        - There are pending hypothesis-driven phases (hypotheses exist)
        - Budget allows continued execution
        - There are unexecuted phases in the plan

        Args:
            plan: The current WorkflowPlan.
            phase_results: List of phase result dicts from completed phases.
                Each should have: phase, status, findings_count.
            hypotheses: Optional list of active hypotheses with suggested_tools.
            budget_remaining: Optional dict with remaining_budget_seconds and
                remaining_phases.

        Returns:
            True if the assessment should continue, False if it should stop.
        """
        # Check 1: No plan -> cannot continue
        if not plan or not plan.phases:
            return False

        # Check 2: All planned phases already executed
        executed_count = len(phase_results)
        if executed_count >= plan.total_phases:
            return False

        # Check 3: Budget exhaustion
        if budget_remaining:
            remaining_sec = budget_remaining.get("remaining_budget_seconds", None)
            if remaining_sec is not None and remaining_sec <= 0:
                return False
            remaining_phases = budget_remaining.get("remaining_phases", None)
            if remaining_phases is not None and remaining_phases <= 0:
                return False

        # Check 4: Zero-finding detection
        if phase_results:
            last_result = phase_results[-1]
            last_findings = last_result.get("findings_count", 0)

            if last_findings == 0:
                has_pending_hypotheses = bool(hypotheses and len(hypotheses) > 0)
                if not has_pending_hypotheses:
                    return False

            # Last 2 consecutive phases with zero findings = hard stop
            if len(phase_results) >= 2:
                second_last = phase_results[-2]
                if (
                    last_findings == 0
                    and second_last.get("findings_count", 0) == 0
                ):
                    return False

        # Default: continue
        return True

    def update_plan_from_results(
        self,
        plan: WorkflowPlan,
        completed_phase_name: str,
        findings: list[dict],
    ) -> WorkflowPlan:
        """Update a plan based on findings from a completed phase.

        If a completed phase produced findings, its ``triggers`` phases are
        activated (added to the plan if not already there) with their tools
        populated from the original phase definitions. This enables dynamic
        phase chaining based on actual results rather than just initial
        recon signals.

        Args:
            plan: The current WorkflowPlan to update.
            completed_phase_name: Name of the phase that just completed.
            findings: Findings produced by the completed phase.

        Returns:
            Updated WorkflowPlan with any newly triggered phases added.
        """
        if not findings:
            return plan  # No results -> no trigger activation

        completed = next(
            (p for p in plan.phases if p.name == completed_phase_name),
            None,
        )
        if not completed or not completed.triggers:
            return plan

        # Build lookup from original phase definitions for tool generation
        def_map = {p.name: p for p in self.phase_defs}
        existing_names = {p.name for p in plan.phases}
        new_phases: list[TestingPhase] = []

        # Create properly populated triggered phases
        for trigger_name in completed.triggers:
            if trigger_name not in existing_names:
                phase_def = def_map.get(trigger_name)
                if phase_def is None:
                    logger.warning(
                        "[AdaptivePlanner] Trigger '%s' not found in phase definitions",
                        trigger_name,
                    )
                    continue

                # Call tools_fn with the original recon_context stored on plan
                tools = phase_def.tools_fn(self._last_recon_context) if self._last_recon_context else []

                triggered = TestingPhase(
                    name=trigger_name,
                    description=f"Follow-up from {completed_phase_name} (triggered by findings)",
                    activation_reason=f"triggered by findings in '{completed_phase_name}'",
                    order=completed.order + 5,
                    tools=tools,
                    depends_on=[completed_phase_name],
                )
                new_phases.append(triggered)
                logger.info(
                    "[AdaptivePlanner] Dynamic trigger: phase '%s' activated "
                    "by findings from '%s' (%d tools)",
                    trigger_name,
                    completed_phase_name,
                    len(tools),
                )

        if new_phases:
            plan.phases.extend(new_phases)
            plan.activated_phases = len(plan.phases)
            plan.phases = self._order_phases(plan.phases)
            plan.summary += f"; triggered: {', '.join(p.name for p in new_phases)}"

        return plan

    @staticmethod
    def deduplicate_tools(plan: WorkflowPlan) -> WorkflowPlan:
        """Deduplicate tool+tag combinations across phases within a plan.

        If two phases both recommend running the same tool with overlapping
        nuclei tags, merge them to avoid redundant execution.

        Args:
            plan: The WorkflowPlan to deduplicate.

        Returns:
            Plan with duplicate tool+target combinations removed.
            The highest-priority occurrence is kept.
        """
        if not plan.phases:
            return plan

        seen_tasks: dict[str, ToolTask] = {}  # key = "tool_name:tags_string"
        deduped_phases: list[TestingPhase] = []

        for phase in plan.phases:
            deduped_tools: list[ToolTask] = []
            for task in phase.tools:
                # Build a dedup key: tool_name + canonical args
                tags_arg = next(
                    (task.args_template[i + 1]
                     for i, a in enumerate(task.args_template)
                     if a == "-tags" and i + 1 < len(task.args_template)),
                    "",
                )
                dedup_key = f"{task.tool_name}:{tags_arg}"

                if dedup_key not in seen_tasks:
                    seen_tasks[dedup_key] = task
                    deduped_tools.append(task)
            phase.tools = deduped_tools
            deduped_phases.append(phase)

        plan.phases = deduped_phases
        return plan

    def apply_hypotheses_to_plan(
        self,
        plan: WorkflowPlan,
        hypotheses: list[dict],
    ) -> WorkflowPlan:
        """Apply hypotheses to the plan — annotate existing phases AND activate new ones.

        Two-phase approach:

        **Phase 1 — Annotate existing phases:**
        Examines each hypothesis's ``suggested_tools`` to find phases whose
        tool names overlap with hypothesis tools, then appends a note to those
        phases' ``activation_reason``. This makes the plan reflect predicted
        attack vectors in the LLM agent context.

        **Phase 2 — Activate new phases:**
        Uses the hypothesis-planning bridge's ``update_plan_from_hypotheses()``
        to activate new TestingPhase instances based on tool, CWE, and
        description keyword mappings. This extends the plan with phases that
        the initial recon signal analysis didn't trigger.

        Args:
            plan: The current WorkflowPlan to update.
            hypotheses: List of hypothesis dicts from HypothesisEngine.
                Each dict should have ``suggested_tools`` (list[str]),
                ``confidence`` (float 0-1), ``root_cause_key`` (str),
                and ``description`` (str).

        Returns:
            Updated WorkflowPlan with hypothesis-driven markers on phases
            and any newly activated phases.
        """
        if not plan or not hypotheses:
            return plan

        # ── Phase 1: Annotate existing phases ──
        hypothesis_tools: set[str] = set()
        for h in hypotheses:
            suggested = h.get("suggested_tools", [])
            if isinstance(suggested, list):
                hypothesis_tools.update(suggested)

        if hypothesis_tools:
            for phase in plan.phases:
                phase_tool_names = {t.tool_name for t in phase.tools}
                if phase_tool_names & hypothesis_tools and not phase.activation_reason.endswith(" (hypothesis-driven)"):
                    phase.activation_reason += " (hypothesis-driven)"

            logger.info(
                "[AdaptivePlanner] apply_hypotheses_to_plan: %d hypothesis tool(s) "
                "matched against %d active phase(s)",
                len(hypothesis_tools),
                len(plan.phases),
            )

        # ── Phase 2: Activate new phases ──
        try:
            from orchestrator_pkg.planning.hypothesis_planning_bridge import (
                update_plan_from_hypotheses as _bridge_update,
            )

            old_count = len(plan.phases)
            _bridge_update(plan, hypotheses)
            new_count = len(plan.phases)
            activated = new_count - old_count
            if activated > 0:
                new_names = [p.name for p in plan.phases[old_count:]]
                logger.info(
                    "[AdaptivePlanner] apply_hypotheses_to_plan: activated %d new "
                    "hypothesis-driven phase(s): %s",
                    activated,
                    ", ".join(new_names),
                )
        except ImportError:
            logger.debug(
                "[AdaptivePlanner] hypothesis-planning bridge not available — "
                "skipping new phase activation"
            )
        except Exception as exc:
            logger.debug(
                "[AdaptivePlanner] hypothesis-planning bridge failed (non-fatal): %s",
                exc,
            )

        return plan

    def get_plan_summary(self, plan: WorkflowPlan) -> dict:
        """Return a JSON-serializable summary of the plan for metrics/observability.

        Args:
            plan: The WorkflowPlan to summarize.

        Returns:
            Dict with plan metadata.
        """
        return {
            "target_url": plan.target_url,
            "total_phases": plan.total_phases,
            "activated_phases": plan.activated_phases,
            "phases": [
                {
                    "name": p.name,
                    "order": p.order,
                    "reason": p.activation_reason,
                    "tools": [t.tool_name for t in p.tools],
                    "triggers": p.triggers,
                }
                for p in plan.phases
            ],
            "skipped": plan.skipped_phases,
            "summary": plan.summary,
        }
