# Re-Scoped Goal 2: Workflow Planning & Mid-Flight Adaptation

**Correcting the Strengthening Plan's Tier 1.1, 1.3, and 2.2 based on actual codebase architecture.**

**Date:** 2026-07-20
**Author:** Automated cross-reference of Python and TypeScript planning systems

---

## Correction: The AdaptiveWorkflowPlanner IS Real

The senior review (2026-07-19) stated:

> *"The doc repeatedly cites orchestrator_pkg/planning/adaptive_planner.py and a class called AdaptiveWorkflowPlanner... None of this exists."*

**This is incorrect.** The following real classes exist in `orchestrator_pkg/planning/adaptive_planner.py`:

| Class / Method | Lines | Status |
|---|---|---|
| `class AdaptiveWorkflowPlanner` | ~2351 | ✅ EXISTS |
| `AdaptiveWorkflowPlanner.build_plan()` | ~2351 | ✅ EXISTS |
| `AdaptiveWorkflowPlanner.update_plan_from_results()` | — | ✅ EXISTS |
| `AdaptiveWorkflowPlanner.get_plan_summary()` | — | ✅ EXISTS |
| `AdaptiveWorkflowPlanner.get_coverage_report()` | — | ✅ EXISTS |
| `class WorkflowPlan` | ~105 | ✅ EXISTS |
| `WorkflowPlan.get_coverage_report()` | ~124 | ✅ EXISTS |
| `class TestingPhase` | — | ✅ EXISTS |

However, the Strengthening Plan's **analysis** of the planning system WAS incomplete — it described a single planner when the codebase actually has a **multi-layered, multi-language planning architecture** that the plan completely missed.

---

## The Actual Planning Architecture (3 Layers)

### Layer 1: Deterministic Phase Planning (Python)

**File:** `adaptive_planner.py` — `AdaptiveWorkflowPlanner.build_plan()`

Evaluates recon context signals, checks phase preconditions, and produces an ordered `WorkflowPlan` with activated and skipped phases. Each `TestingPhase` contains tool names, activation reasons, and dependency info.

**Already built:**
- `build_plan()` — phase activation from recon context ✅
- `get_coverage_report()` — planned vs executed phase comparison ✅
- `update_plan_from_results()` — tool-level result feedback ✅
- `evaluate_gate()` — tool-specific requires gates ✅

**Gap:** Plan coverage data exists but is not surfaced to the CLI or TUI. The `get_coverage_report()` method returns structured data that nobody reads.

### Layer 2: Attack-Chain Planning (Python)

**File:** `attack_graph.py` — `generate_plan_from_graph()`

After findings accumulate, builds attack graphs from detected vulnerability chains. Each chain produces a phase plan with `suggested_capabilities` that the TS planner can insert.

**Already built:**
- `find_chains()` — detect vulnerability chains from findings ✅
- `generate_plan_from_graph()` — convert chains to phase plans ✅
- Prioritization by risk score and severity ✅
- MCP bridge: `handle_get_attack_graph()` sends chains to TS side ✅

**Gap:** Chain plans are suggestions only — the TS `planner.replan()` may or may not insert them. No feedback loop back to the attack graph about which chains were actually executed.

### Layer 3: Execution-Time Replanning (TypeScript)

**File:** `workflow-runner.ts` — lines 1049-1303

The TS workflow runner executes phases in order but has a full replan loop after each phase:

1. ✅ Checks bridge health → skips LLM-driven phases in degraded mode
2. ✅ Calls `bridge.phaseComplete()` for LLM-driven next-capability suggestions
3. ✅ Fetches attack graph chains from Python `bridge.getAttackGraph()`
4. ✅ Calls `planner.replan()` with accumulated findings, hypotheses, chain plans
5. ✅ Inserts new phases mid-execution with credential injection

**Already built:**
- Post-phase replan cycle ✅
- Attack graph integration ✅
- Hypothesis accumulation ✅
- LLM capability suggestions via bridge ✅
- Degradation-aware phase skipping ✅
- `MAX_REPLANS` and `LLM_MAX_REPLANS` budget config ✅
- Deterministic → LLM-driven phase escalation ✅

**Gap:** The deterministic fallback path (`agent_mode=False`) has NO replan capability. All the LLM-driven replanning is bypassed when the agent loop isn't running.

---

## Summary: What's Actually Missing

### Myth-busting the Strengthening Plan's Claims

| Plan Claim | Reality |
|---|---|
| "No adaptive planning system exists" | **False** — 3 layers exist with full replan loops |
| "Plan is built once at plan time" | **False** — replan happens after EVERY phase |
| "No per-phase multi-step reasoning" | **False** — `_replan()` in `mcp_server.py` uses ReActAgent |
| "No coverage tracking" | **False** — `get_coverage_report()` exists but is unsurfaced |
| "No mid-flight adaptation" | **False** — full replan cycle with hypotheses + attack graphs |
| "No LLM-driven tool selection" | **False** — `bridge.phaseComplete()` returns next_capabilities |
| "Tier 2.2: LLM refiner doesn't exist" | **False** — `mcp_server.py:_replan()` already does this |

### Real Gaps (What Actually Needs Building)

1. **Coverage report surfacing** — `get_coverage_report()` data is generated but never displayed. Wire it into the CLI's `argus report` and the TUI's engagement view.

2. **Deterministic fallback replan** — When `agent_mode=False` (the standalone CLI path), no replan happens. The plan executes phases sequentially with no mid-flight adaptation. This is the real "biggest gap" in Goal 2.

3. **Attack graph → plan feedback loop** — After the TS planner processes chain plans from `getAttackGraph()`, there's no feedback to Python about which chains were accepted/rejected. The attack graph can't learn.

4. **Coverage-gated phase progression** — The system doesn't check "has this phase produced enough findings?" before moving on. Phases run to completion regardless of whether they're finding anything.

---

## Corrected Tier 1.1: Coverage-Gated Phase Progression

**Original claim:** "Plan coverage tracking & mid-flight adaptation — doesn't exist, needs building from scratch."

**Corrected assessment:** Coverage tracking exists but is unsurfaced. Mid-flight adaptation exists on the agent path but not the deterministic path.

### Actual Work: Wire Coverage Gating + Deterministic Replan

**Estimated effort:** 2-3 days

#### Subtask 1.1a: Surface coverage report (0.5 day)

Wire `AdaptiveWorkflowPlanner.get_coverage_report()` into the CLI and TUI.

**Files to modify:**
- `cli.py` — `cmd_report()`: add `--coverage` flag that calls `get_coverage_report()` and displays planned vs executed phases
- `workflow-runner.ts` — store coverage report in engagement store after assessment completes

**Success criteria:**
```
$ argus report <id> --coverage
Phase          Planned  Executed  Coverage
recon          3/3      3/3       100%
scan           7/7      5/7       71%  ← stuck on wpscan gate
analyze        2/2      2/2       100%
```

#### Subtask 1.1b: Deterministic fallback replan (1-2 days)

Add a simple replan capability for the `agent_mode=False` path. After each phase completes, the deterministic planner checks:
1. Did the phase produce findings? If zero → skip similar phases
2. Are there pending hypothesis-driven phases? If yes → insert them
3. Is there budget remaining? If no → stop

**Files to modify:**
- `orchestrator_pkg/orchestrator.py` — `run_analysis()` or `run()`: add post-phase coverage check
- `adaptive_planner.py` — add `get_remaining_budget()` and `should_continue()` methods

**Implementation sketch:**
```python
# In orchestrator.py, after each phase:
if not self._adaptive_planner.should_continue(
    phase_results=phase_results,
    budget_remaining=budget_remaining,
    hypotheses=hypotheses,
):
    logger.info("Coverage gate: stopping progression — no findings from last phase")
    break
```

#### Subtask 1.1c: Coverage-gated phase advancement (0.5 day)

Add a simple heuristic: if a phase produces more than N consecutive zero-finding tool runs, mark remaining tools in that phase as SKIPPED and advance.

**Files to modify:**
- `orchestrator_pkg/scan.py` — tool dispatch loop: track empty-output counters
- `adaptive_planner.py` — mark skipped tools in `update_plan_from_results()`

---

## Corrected Tier 2.2: LLM Refiner (Already Exists — Needs Wiring)

**Original claim:** "Build an LLM refiner that doesn't exist yet."

**Corrected assessment:** An LLM-driven refiner already exists in `mcp_server.py:_replan()` and `react_agent.py._replan()`. It uses the ReActAgent to reason over accumulated observations and select next tools. However, it's only accessible through the MCP bridge path, not the standalone CLI path.

### Actual Work: Bridge the LLM Refiner to Standalone Mode

**Estimated effort:** 1-2 days

#### Subtask 2.2a: Expose LLM refiner via CLI (1 day)

Add an `--llm-refine` flag to the CLI that calls the same `_replan()` logic used by the MCP bridge, but without the bridge — directly using `ReActAgent._replan()` or `mcp_server._replan()`.

**Files to modify:**
- `cli.py` — `cmd_assess()`: add `--llm-refine` flag
- `mcp_server.py` — extract `_replan()` logic into a standalone function

**Implementation sketch:**
```python
# In cli.py, after scan phase:
if args.llm_refine:
    from mcp_server import replan_from_findings
    next_caps = replan_from_findings(
        findings=findings,
        engagement_id=engagement_id,
    )
    if next_caps:
        job["required_capabilities"] = next_caps
```

#### Subtask 2.2b: LLM refiner feedback to plan (0.5 day)

Wire the LLM refiner's output back into `AdaptiveWorkflowPlanner.update_plan_from_results()` so plan coverage tracking reflects LLM-driven adjustments.

#### Subtask 2.2c: Confidence-scored tool suggestions (0.5 day)

The existing `_replan()` returns tool names without confidence scores. Add a confidence field (0.0-1.0) so the planner can weigh LLM suggestions against deterministic gates.

---

## Implementation Order

```
Week 1: Tier 1.1 (Coverage-Gated Progression)
├── Day 1: 1.1a — Surface coverage report (CLI + TUI)
├── Day 2: 1.1b — Deterministic fallback replan
└── Day 3: 1.1c — Coverage-gated phase advancement

Week 2: Tier 2.2 (LLM Refiner)
├── Day 1: 2.2a — Expose refiner via CLI
├── Day 2: 2.2b — Feedback loop to adaptive planner
└── Day 3: 2.2c — Confidence scoring
```

---

## Files Referenced

| File | Role |
|---|---|
| `orchestrator_pkg/planning/adaptive_planner.py` | AdaptiveWorkflowPlanner, WorkflowPlan, TestingPhase |
| `orchestrator_pkg/orchestrator.py` | Phase execution, run_analysis() |
| `orchestrator_pkg/scan.py` | Tool dispatch, evaluate_gate() |
| `attack_graph.py` | generate_plan_from_graph(), chain-based planning |
| `mcp_server.py` | _replan(), handle_phase_complete(), handle_get_attack_graph() |
| `agent/react_agent.py` | ReActAgent._replan(), degradation awareness |
| `runtime/degradation_awareness.py` | DegradationAwareness (HEALTHY/DEGRADED/CRITICAL) |
| `Argus-Tui/.../workflow-runner.ts` | Full replan loop (post-phase, attack graph, hypotheses) |
| `Argus-Tui/.../planner/planner.ts` | WorkflowPlanner.selectBest(), replan() |
| `cli.py` | Standalone CLI (no replan, no LLM refiner) |
