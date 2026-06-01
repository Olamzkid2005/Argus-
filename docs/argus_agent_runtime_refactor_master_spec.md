c /c# Argus Runtime Refactor Master Specification — v3

> **Revision notice:** v3 incorporates a deep codebase audit against actual code
> in `argus-workers/`. v1 made several incorrect assumptions about the existing
> architecture (e.g., claimed attack graph didn't exist, claimed tool registry
> lacked metadata). v2/v3 correct these inaccuracies and add governance
> principles for safe execution of the refactor.

---

## Objective

This document defines the architectural refactor required to transform Argus
from a partially pipeline-centric AI security platform into a fully agent-first
autonomous security runtime with deterministic fallback support.

The intended architecture is:

```text
PRIMARY:
LLM ReAct Runtime

FALLBACK:
Deterministic Pipeline Executor
```

The deterministic pipeline must ONLY activate when:
- LLM is unavailable
- Agent execution fails
- Agent mode is disabled
- Cost/safety guard triggers

The deterministic pipeline MUST NOT leak orchestration assumptions into the
primary runtime path.

---

# SECTION 0 — REFACTOR GOVERNANCE PRINCIPLES

This section defines *how* the refactor is executed, not *what* the
refactor builds. These principles prevent regressions and ensure safe
transition.

## Principle 1 — Feature Flags for Every Phase

Every phase MUST be gated behind a feature flag in `feature_flags.py`:

```python
FEATURE_ENGAGEMENT_STATE = "ENGAGEMENT_STATE"
FEATURE_TRUE_REACT_LOOP = "TRUE_REACT_LOOP"
FEATURE_CLEAN_ORCHESTRATOR = "CLEAN_ORCHESTRATOR"
FEATURE_ATTACK_GRAPH_V2 = "ATTACK_GRAPH_V2"
FEATURE_MEMORY_RETRIEVAL = "MEMORY_RETRIEVAL"
FEATURE_GOVERNANCE_V2 = "GOVERNANCE_V2"
```

This enables:
- Per-engagement gradual rollout (Phase X enabled for engagement Y)
- Instant rollback without revert commits
- A/B comparison: old path vs new path producing same results

## Principle 2 — Shadow-Mode Validation

Before switching to any new component, run it in parallel with the old
component and compare outputs:

```python
shadow_result = new_engagement_state.build()
old_result = old_legacy_approach()
if shadow_result != old_result:
    logger.critical("SHADOW_MISMATCH: phase=%s engagement=%s", phase, eid)
    emit_alert(...)
else:
    logger.info("SHADOW_OK: phase=%s engagement=%s", phase, eid)
```

Shadow-mode MUST pass for 100 consecutive test engagements before the new
path becomes the default. This prevents silent regressions.

## Principle 3 — Testing Gates

Each phase has a mandatory testing gate that must pass before the next phase
can begin:

| Phase | Testing Gate |
|-------|-------------|
| Phase 1 | `pytest tests/` — all existing tests pass. `shadow_compare(EngagementState, legacy_state)` — no diff for 100 engagements |
| Phase 2 | `pytest tests/test_scanning_pipeline.py tests/test_orchestrator_integration.py` — all pass. End-to-end test: same target scanned with old and new loop produces same findings |
| Phase 3 | `pytest tests/` — all pass. Orchestrator unit tests verify it no longer makes decisions |
| Phase 4 | `pytest tests/test_attack_graph.py` — all pass. Attack graph chains are strictly additive (no regressions in existing chain detection) |
| Phase 5 | Memory retrieval returns results consistent with direct DB queries |
| Phase 6 | `pytest tests/` — all pass. Tool sandbox integration test passes |

## Principle 4 — In-Flight Engagement Migration

When each phase deploys, in-flight engagements must transition gracefully:

- **Phase 1**: Existing engagements continue using old state paths. New
  engagements use `EngagementState`. After all in-flight engagements
  complete, the old paths are removed.
- **Phase 2**: The new loop only activates for new engagements created
  after the deploy timestamp. In-flight engagements (still in
  recon/scan/analysis when Phase 2 ships) finish under the old batch
  dispatch system.
- **Phase 3-6**: Same pattern — gate on `engagement.created_at < rollout_date`.

This is NON-optional. Do NOT attempt to migrate in-flight state — the risk
of corruption exceeds the benefit.

---

# SECTION 1 — CRITICAL ARCHITECTURAL GOALS

## Goal 1 — Single Runtime Authority

The repository currently has fragmented execution ownership.

Decision-making exists across:
- `ReActAgent` (`agent/react_agent.py`) — tool selection during scan phase
- `IntelligenceEngine` (`intelligence_engine.py`) — post-scan analysis &
  action generation (recon_expand, deep_scan, auth_focused_scan)
- `Orchestrator` (`orchestrator_pkg/orchestrator.py`) — scan mode selection
  (swarm vs agent vs deterministic), budget routing, phase transitions
- Celery task flow (`tasks/analyze.py`) — batch action dispatch & state
  transitions

**Key insight from codebase audit:** The *actual* decision-making hierarchy is different from what v1 assumed:
- `IntelligenceEngine` is the primary strategic decision-maker for
  post-recon/scan actions (deep_scan, recon_expand, auth_focused_scan)
- `ReActAgent` is the tactical tool-selector *within* the scan phase only
- `Orchestrator` still selects scan mode (`swarm` vs `agent` vs
  `deterministic`) in its `run_scan()` method

### Required Outcome

The ONLY primary decision-maker should be `ReActAgent` — not only for tool
selection but for the full engagement lifecycle.

The `IntelligenceEngine` becomes a component *called by* the agent for
analysis, not an independent decision-maker.

The orchestrator becomes:

```text
execution-only runtime layer
```

The deterministic pipeline becomes:

```text
fallback-only planning layer
```

---

## Goal 2 — Replace Batch Planning With True ReAct Runtime

Current implementation still behaves like:

```python
actions = result.get("actions", [])
for action in actions:
```

This is in `IntelligenceEngine.generate_actions()` which returns a batch of
3 action types (`recon_expand`, `deep_scan`, `auth_focused_scan`), dispatched
via `tasks/analyze.py` in a `for` loop.

The correct runtime model is:

```python
while engagement_active:
    observation = state.collect_latest_observation()

    action = agent.plan(observation)

    if action.type == "STOP":
        break

    result = execute(action)

    state.update(result)
```

The LLM must reason after EVERY observation.

Never pre-materialize large action batches.

---

## Goal 3 — Introduce Canonical EngagementState

Current system state is fragmented across:
- Postgres: `engagements`, `findings`, `engagement_states`, `loop_budgets`,
  `decision_snapshots` tables
- Redis: `ReconContext` serialization (`tasks/utils.py` — `save_recon_context`/
  `load_recon_context`)
- Celery task memory: `self.history` in `ReActAgent`, budget state in
  `LoopBudgetManager`
- WebSocket streams: `StreamManager._history` in `streaming.py`
- Orchestrator instance memory: `_last_agent_tried_tools`, `_bug_bounty_mode`

This creates execution drift across worker restarts and retries.

A canonical runtime state object MUST exist.

---

# SECTION 2 — ENGAGEMENT STATE SYSTEM

## Create Canonical Runtime State

### Required File

```text
argus-workers/runtime/engagement_state.py
```

### Required Class

```python
class EngagementState:
    engagement_id: str

    recon_context: dict

    findings: list

    observations: list

    hypotheses: list

    tool_history: list

    failed_actions: list

    attack_graph: dict

    confidence_scores: dict

    memory_summary: str

    current_goal: str

    current_phase: str

    execution_iteration: int

    state_version: int
```

**Integration requirement:** The state must integrate with existing persistence rather than replacing it from scratch:

- `EngagementStateMachine` (`state_machine.py`) already provides state
  transition logic — the new `EngagementState` should wrap it, not replace it.
- `LoopBudgetManager` (`loop_budget_manager.py`) already persists budget
  state to the `loop_budgets` table — `EngagementState` should consume it.
- `ReconContext` (`models/recon_context.py`) already has `to_dict()` /
  `from_dict()` — reuse these serialization methods.

---

## Mandatory Rules

### Rule 1

ALL runtime reads MUST come from EngagementState.

No direct runtime reasoning from:
- Redis
- websocket state
- raw task memory

### Rule 2

EngagementState must be persisted transactionally.

Required persistence:
- Redis for fast access
- Postgres snapshots for durability

### Rule 3

Every mutation increments:

```python
state_version += 1
```

### Rule 4

Every tool execution MUST append:

```python
ToolExecutionRecord
```

containing:
- tool
- args
- timestamp
- result summary
- token usage
- execution cost
- failure state

---

# SECTION 3 — AGENT-FIRST EXECUTION MODEL

## Required Runtime Hierarchy

### Primary Runtime

```text
ReActAgent
```

### Fallback Runtime

```text
DeterministicPipelineExecutor
```

### Runtime Selection Logic

```python
if llm_available and agent_mode_enabled:
    runtime = ReActAgentRuntime
else:
    runtime = DeterministicRuntime
```

**Current reality:** The orchestrator already implements a 3-tier
mode selection in `run_scan()`:
1. `scan_mode == "swarm"` → `_run_swarm_scan()` (parallel specialist agents)
2. `agent_mode_enabled` → `_run_agent_scan()` (ReActAgent loop + safety net)
3. Fallback → `_run_deterministic_scan()` (pipeline-only)

This 3-tier structure is close to the spec's goal but must be simplified to
2 tiers (primary + fallback). The swarm mode should be an agent capability,
not a separate orchestrator method.

---

## Strict Runtime Ownership

### ReActAgent Responsibilities

The ReActAgent is responsible for:
- tool selection
- reasoning
- hypothesis generation
- dynamic planning
- exploit chaining
- stop conditions
- adaptive strategy
- calling IntelligenceEngine for analysis when needed (not the other way around)

### Orchestrator Responsibilities

The orchestrator is responsible ONLY for:
- task execution
- retries
- timeout enforcement
- queue coordination
- persistence
- streaming

The orchestrator MUST NEVER:
- decide scan strategy
- select tools
- infer attack paths
- branch scan logic semantically
- choose between swarm/agent/deterministic modes

### Deterministic Runtime Responsibilities

The deterministic runtime exists ONLY for:
- fallback execution
- emergency degraded mode
- low-cost scans
- testing

It MUST NOT influence primary runtime logic.

---

# SECTION 4 — TRUE STEPWISE REACT LOOP

## Required Runtime Flow

### Replace Current Batch Action Dispatch

Remove:

```python
for action in actions:
```

**(currently in `tasks/analyze.py` dispatching `IntelligenceEngine` actions)**

Replace with:

```python
while not state.is_complete():

    observation = state.build_observation()

    action = agent.next_action(observation)

    if action.type == "STOP":
        break

    result = executor.execute(action)

    state.apply(result)

    persistence.save(state)
```

**Current reality:** The `ReActAgent` already has a single-step loop for the scan
phase (see `react_agent.py` `run()` method). The refactor needed is to make
this loop control *the entire engagement lifecycle* — not just tool selection
within one phase.

---

## Required Observation Model

Each observation must include:
- latest findings
- recent failures
- tool history
- attack graph state
- confidence updates
- rate limit warnings
- auth discoveries
- token budget status
- execution cost

**Current reality:** The agent already builds observations via `build_observation_summary()`
in `agent/agent_prompts.py` and stores them in `self.history`. These are
capped at 2000 chars per entry and 50 entries total. The refactor should
replace this ad-hoc approach with the canonical `EngagementState`.

---

## Required Agent Output Schema

```python
class AgentAction:
    action_id: str

    tool: str

    arguments: dict

    reasoning: str

    confidence: float

    estimated_cost: float

    estimated_runtime: int

    expected_signal: str
```

**Current reality:** `AgentAction` (`agent/agent_action.py`) currently has:
`tool`, `arguments`, `reasoning`, `cost_usd`. Missing: `action_id`,
`confidence`, `estimated_runtime`, `expected_signal`. These gaps are
consistent with the spec's requirements.

---

# SECTION 5 — REPLAY-SAFE COGNITION

## Problem

Celery retries currently break cognitive continuity.

The agent can reason differently during retries.

**Current reality:** The v1 spec correctly identifies this gap. `task_error_boundary`
in `tasks/base.py` stores error classifications but no decision checkpoints.
A Celery retry re-runs the task from scratch, potentially making different LLM
calls. The override of `BaseTask.retry()` in `celery_app.py` now injects
classification-based `retry_delay_seconds`, but this is a tactical fix, not
the architectural solution needed.

---

## Required Solution

Every agent action MUST persist:

```python
DecisionCheckpoint
```

containing:
- action_id
- observation_hash
- reasoning_hash
- selected_tool
- args
- timestamp
- state_version

---

## Retry Rules

### Rule 1

Retries MUST replay the original decision.

They MUST NOT re-prompt the LLM.

### Rule 2

Only failed execution is replayed.

Reasoning state remains frozen.

### Rule 3

Agent re-planning only occurs AFTER:
- execution completion
- timeout
- fatal failure

---

# SECTION 6 — TRANSACTIONAL EVENT STREAMING

## Problem

WebSocket events can emit before durable persistence.

This creates phantom findings.

## Required Rule

The system MUST follow:

```text
persist -> commit -> emit
```

NOT:

```text
emit -> persist
```

**Current reality:** The streaming layer (`streaming.py`) emits tool start/
complete events via `emit_tool_start()` / `emit_tool_complete()`. The
Orchestrator saves findings via `_save_findings()` and then returns the result
dict. There is no strict ordering guarantee — the WebSocket publisher could
emit before the DB commit completes. This section is correct as-is.

---

## Required Streaming Sequence

### Correct Order

1. Tool execution completes
2. Result persisted
3. DB commit succeeds
4. EngagementState updated
5. websocket/SSE event emitted

---

# SECTION 7 — TOOL CAPABILITY REGISTRY

## Problem

Tools currently lack semantic metadata.

This weakens agent planning quality.

## Required Tool Schema

Every tool definition MUST include:

```python
ToolMetadata(
    name,
    category,
    risk_level,
    requires_auth,
    estimated_runtime,
    estimated_cost,
    concurrency_limit,
    scope_sensitivity,
    exploit_categories,
    output_signal_quality,
    rate_limit_impact,
    allowed_targets,
)
```

**Key insight from codebase audit — the registry is richer than v1 assumed:**

`tool_definitions.py` already has:
- `ToolDefinition` dataclass with `signal_quality` (CONFIRMED/PROBABLE/CANDIDATE)
- `ToolRequires` activation conditions (`tech_contains`, `recon_signals`,
  `target_scheme`)
- `ToolParameter` schemas with types, enums, defaults
- `ALL_PHASES` tuple for phase-based tool grouping
- `evaluate_gate()` for activation-gate checking

**What's still missing** from the spec's wishlist:
- `risk_level` (per-tool safety rating)
- `estimated_cost` (dollar cost per invocation)
- `estimated_runtime` (seconds — currently only `timeout` exists)
- `concurrency_limit`
- `scope_sensitivity`
- `exploit_categories`
- `rate_limit_impact`

**Strategy:** Evolve `ToolDefinition` to include these fields rather than
creating a separate `ToolMetadata` class.

---

## Required Planning Constraints

The LLM MUST reason using:
- runtime cost
- signal quality
- risk level
- scan redundancy
- exploit category coverage

---

# SECTION 8 — ATTACK GRAPH ENGINE

## Problem

Findings are currently too flat.

Argus needs exploit relationship modeling.

## Required System

```text
attack_graph_engine.py
```

**Key insight from codebase audit — `attack_graph.py` already exists** with a complete
implementation:

- `Node`, `Edge`, `Path` classes with CVSS, confidence, correlation factors
- `AttackGraph.compute_risk()` with confidence decay math
- `AttackGraph.find_chains()` — Bug-Reaper chain detection (8 chain rules:
  SSRF→IMDS, XSS+CSRF→ATO, etc.)
- `AttackGraph.get_highest_risk_paths()` — path risk ranking

**The spec should EVOLVE the existing code, not create from scratch.**

### Required Evolution of `attack_graph.py`

Add to `AttackNode`:
- `prerequisites: list[str]` — conditions that must be true for this finding
  to be exploitable
- `downstream_impacts: list[str]` — what this finding enables

Add to `AttackEdge`:
- `relationship_type: str` — "enables", "bypasses", "amplifies", "chains"

---

## Required Capability

Model:

```text
Finding A enables Finding B
```

Examples:

```text
SSRF -> internal metadata access -> credential theft

Open Redirect -> OAuth abuse -> account takeover

XSS -> session theft -> privilege escalation
```

---

## Required Node Model

```python
class AttackNode:
    finding_id
    exploitability
    prerequisites       # NEW: conditions enabling this finding
    downstream_impacts  # NEW: what this finding enables downstream
    confidence
```

---

## Required Edge Model

```python
class AttackEdge:
    source
    target
    relationship_type  # NEW: "enables" | "bypasses" | "amplifies" | "chains"
    confidence
```

---

# SECTION 9 — MEMORY SYSTEM

## Problem

Long engagements will exceed token limits.

Current runtime lacks semantic memory compression.

**Current state in the codebase:**
- **Short-term:** `ReActAgent.history` (list, capped to 50 entries, 2000
  chars each) — already exists but is ephemeral (lost on worker restart)
- **Medium-term:** `decision_snapshots` table in Postgres (set by
  `SnapshotManager`) — exists but not consumed by the agent
- **Long-term:** `target_profiles` table (via `TargetProfileRepository`) —
  exists but not yet fed into agent prompts as memory retrieval

---

## Required Memory Architecture

### Short-Term Memory

Recent observations.

Stored in `EngagementState.observations` (replaces `ReActAgent.history`).

### Medium-Term Memory

Compressed reasoning summaries.

Stored in `decision_snapshots` table (already exists — needs retrieval API).

### Long-Term Memory

Retrievable historical findings.

Stored in `target_profiles` table (already exists — needs injection into
agent prompts).

**Current state:** `target_profile` is partially injected into the ReActAgent prompt
via `build_tool_selection_prompt()` (prompts.py section "What We Know About
This Target"). This is a good start — extend to full memory retrieval.

---

## Required Retrieval Layer

Agent prompts must retrieve:
- related findings
- historical attack chains
- prior failed hypotheses
- successful exploit patterns

---

# SECTION 10 — SAFETY & EXECUTION CONTROLS

## Mandatory Safety Controls

### Control 1 — Tool Sandbox

Every scan tool MUST execute inside:
- Docker
- isolated namespace
- restricted network policy

**Current state:** `ToolRunner` runs tools as subprocesses on the host
system. The `SandboxRuntime` (from early code) was deprecated. There is no
Docker-level isolation for individual tool executions.

### Control 2 — Scope Enforcement

Every request MUST validate:
- allowed domains
- allowed ports
- allowed IP ranges

before execution.

**Current state:** Scope validation already exists in `tools/scope_validator.py`:
- `ScopeValidator` class with `validate_target()` method
- Integrated into `run_scan_with_agent()` via `scoped_call` wrapper
- `ScopeViolationError` exception
- Also a `validate_target_scope()` function used in swarm agents

The refactor should make scope validation a **mandatory middleware layer** in
`ToolRunner`, not optional per-call wrappers.

### Control 3 — Loop Suppression

Prevent:
- repetitive low-signal scans
- recursive tool selection
- exploit spam

**Current state:** Partial loop suppression exists via `LoopBudgetManager`:
- `max_cycles`, `max_depth`, `max_llm_reviews` limits
- Persisted to `loop_budgets` table after every `consume()`
- "Budget exhausted" logic in `run_analysis()` that checks for meaningful
  approved actions

The spec should codify this and add a "low-signal threshold" (e.g. stop if
last 3 tool runs produced only INFO/low-severity findings).

### Control 4 — Cost Governance

Agent runtime MUST terminate when:
- token budget exceeded
- runtime budget exceeded
- low-signal threshold reached

**Current state:** Cost governance already partially exists:
- `LLM_AGENT_MAX_COST_USD` in `agent_config.py` — stops agent if cost exceeds
  threshold, switches to deterministic fallback
- `LlmCostTracker` in `tasks/utils.py` — Redis-backed per-engagement LLM cost
  tracking with `record_llm_call()` and `has_remaining_budget()`
- `HardTimeoutSeconds` in orchestrator — raises `EngagementTimeoutError`

No centralized cost governance layer exists that ties these together.

---

# SECTION 11 — CLEAN FALLBACK ARCHITECTURE

## Required Runtime Separation

### Agent Runtime

```text
agent_runtime.py
```

### Deterministic Runtime

```text
deterministic_runtime.py
```

### Shared Executor

```text
execution_engine.py
```

## Strict Rule

The deterministic runtime MUST NOT leak planning assumptions into:
- orchestrator
- execution layer
- EngagementState
- streaming layer

It exists ONLY as:

```text
fallback runtime
```

**Current reality:** The orchestrator's `run_scan()` already has the
fallback pattern:

```python
if agent_mode_enabled and _recon_ok and _llm_ok:
    findings = self._run_agent_scan(...)       # agent primary
else:
    findings = self._run_deterministic_scan(...)  # deterministic fallback
```

And `_run_agent_scan()` itself runs a safety-net deterministic pipeline AFTER
the agent:

```python
findings = self.run_scan_with_agent(...)          # agent primary
deterministic_findings = execute_scan_pipeline(   # deterministic safety net
    self, ..., skip_tools=agent_tried
)
findings.extend(deterministic_findings)
```

The structural problem is NOT that fallback doesn't exist — it's that:
1. The **orchestrator** makes the mode decision (violating Goal 1)
2. The **safety net pattern** (`agent + deterministic`) is right conceptually
   but wrong architecturally (orchestrator orchestrates it, not the agent)
3. There's no **shared executor** — the agent calls `ToolRegistry.call()` and
   the pipeline calls `ToolRunner.run()` via `pipeline_router.py`

---

# SECTION 12 — REQUIRED REFACTOR TASKS

## PHASE 1 — CORE STATE REFACTOR

Required:
- Build `EngagementState` wrapping `EngagementStateMachine` +
  `LoopBudgetManager` + `ReconContext`
- Remove fragmented runtime state (Redis raw reads, Celery task memory,
  orchestrator instance vars)
- Introduce versioned snapshots with `state_version` increment
- Add action IDs to `AgentAction`
- Normalize `db_cursor()` usage (mix of `db_cursor()`, `connect()`,
  `get_db().get_connection()`, raw `psycopg2` calls)

**Files affected:**
- `runtime/engagement_state.py` (NEW)
- `agent/agent_action.py` (add `action_id`, `confidence`,
  `estimated_runtime`, `expected_signal`)
- `agent/react_agent.py` (migrate `self.history` → `EngagementState`)
- `orchestrator_pkg/orchestrator.py` (remove in-memory state:
  `_last_agent_tried_tools`, `_bug_bounty_mode`)
- `database/connection.py` (standardize cursor API)

---

## PHASE 2 — TRUE REACT LOOP

Required:
- Remove batch action execution from `IntelligenceEngine.generate_actions()` /
  `tasks/analyze.py`
- Implement single-step reasoning loop over entire engagement lifecycle
- Add observation rebuild system from `EngagementState.build_observation()`
- Add replay-safe checkpoints (`DecisionCheckpoint` table)
- `IntelligenceEngine` becomes a **component** called by the agent loop
  (currently the agent is called by the orchestrator during scan, and
  `IntelligenceEngine` is called separately during analysis — they should be
  unified in one loop)

**Files affected:**
- `intelligence_engine.py` (strip `generate_actions()`, expose as
  `analyze_state(state)` — returns analysis, not actions)
- `tasks/analyze.py` (remove batch dispatch loop — replace with agent loop)
- `agent/react_agent.py` (extend `run()` to control full engagement
  lifecycle, not just scan-phase tool selection)
- `orchestrator_pkg/orchestrator.py` (remove mode-selection logic from
  `run_scan()`)
- `runtime/decision_checkpoint.py` (NEW — `DecisionCheckpoint` dataclass
  + DB persistence)

**Testing gate:** `pytest tests/test_scanning_pipeline.py tests/test_orchestrator_integration.py`
  — all pass. End-to-end: scan same target with old batch dispatch and new
  single-step loop. Findings must be identical (superset allowed, not subset).

**Migration:** Feature-flag `TRUE_REACT_LOOP`. Old engagements finish under
  batch dispatch. New engagements use true ReAct loop.

---

## PHASE 3 — ORCHESTRATION CLEANUP

Required:
- Remove decision logic from orchestrator (`run_scan()` mode selection,
  `_run_swarm_scan` / `_run_agent_scan` / `_run_deterministic_scan`
  branching)
- Move all strategy into `ReActAgent` (agent decides its mode — swarm vs
  single-agent vs deterministic-fallback)
- Isolate deterministic fallback runtime (`deterministic_runtime.py`)
- Create shared `execution_engine.py` for both agent and deterministic paths
- Fold `CoordinatorAgent` class into `ReActAgent` — the class
  (`agent/coordinator.py`) is a thin delegation wrapper with no unique
  behavior. However, the standalone `create_phase_agent()` function is USED
  by `orchestrator.run_scan_with_agent()` and must be preserved or moved
  into `agent/react_agent.py`.
- Extract swarm agent activation from `orchestrator._run_swarm_scan()`
  into the agent runtime. The agent should decide whether to activate swarm
  specialists, not the orchestrator.
- Create shared `execution_engine.py` for both agent and deterministic paths

**Files affected:**
- `orchestrator_pkg/orchestrator.py` (strip to pure execution + persistence)
- `agent/coordinator.py` (gut the class; preserve `create_phase_agent()`
  function if still needed, or move into `react_agent.py`)
- `agent/swarm.py` (move activation decision into `SwarmOrchestrator`,
  remove orchestrator's `_run_swarm_scan()`)
- `runtime/deterministic_runtime.py` (NEW — extracted from
  `orchestrator._run_deterministic_scan`)
- `runtime/execution_engine.py` (NEW — shared tool dispatch + result
  recording. Used by both agent and deterministic paths. Wraps
  `ToolRunner.run()` with scope validation middleware.)
- `agent/react_agent.py` (take over mode selection — decides whether to
  activate swarm, run single-agent, or fall back to deterministic)

**Testing gate:** `pytest tests/` — all pass. Orchestrator unit tests
  verify it no longer makes strategic decisions (no `if scan_mode ==`
  branching, no strategy logic).

**Migration:** `CLEAN_ORCHESTRATOR` feature flag. Shadow-compare:
  orchestrate via old orchestrator vs new agent-driven path for same
  engagement. Findings must match.

---

## PHASE 4 — ATTACK GRAPH ENGINE

Required:
- **Evolve** existing `attack_graph.py` — do NOT create from scratch
- Add `AttackNode.prerequisites`, `AttackNode.downstream_impacts`
- Add `AttackEdge.relationship_type` ("enables", "bypasses", "amplifies",
  "chains")
- Integrate attack graph into `EngagementState` as a first-class component
- Expose attack graph paths to agent observation builder

**Files affected:**
- `attack_graph.py` (add prerequisite/impact/relationship fields)
- `runtime/engagement_state.py` (integrate attack graph)
- `agent/agent_prompts.py` (include attack paths in observation)

**Testing gate:** `pytest tests/test_attack_graph.py` — all pass. Attack
  graph chains are strictly additive (no regressions in existing chain
  detection — new relationships only add edges, never remove them).

**Migration:** `ATTACK_GRAPH_V2` feature flag. Old code path untouched.
  Evolve existing classes; the old API continues to work.

---

## PHASE 5 — MEMORY & RETRIEVAL

Required:
- Keep `ReActAgent.history` as short-term memory (migrate to
  `EngagementState.observations`)
- Add medium-term compression from `decision_snapshots` table (create
  retrieval API: `MemoryRetriever.get_relevant_context(state)`)
- Add long-term retrieval from `target_profiles` table (extend existing
  injection in `build_tool_selection_prompt()`)
- Build `MemoryRetriever` component with semantic search across all 3 tiers

**Files affected:**
- `runtime/memory.py` (NEW — `MemoryRetriever` with 3-tier retrieval)
- `runtime/engagement_state.py` (integrate memory)
- `agent/agent_prompts.py` (inject memory into prompts)
- `database/repositories/target_profile_repository.py` (add retrieval queries)

**Testing gate:** Memory retrieval tests: verify that `MemoryRetriever`
  returns results consistent with direct DB queries for the same context.
  Latency budget: <50ms per retrieval call.

**Migration:** `MEMORY_RETRIEVAL` feature flag. Injection into prompts
  is additive — removing memory context produces the same agent behavior
  as before (just with less context for the LLM).

---

## PHASE 6 — SAFETY HARDENING

> **Note:** Phase 6 is partially dependent on Phase 3 — the
> `execution_engine.py` created in Phase 3 should accept middleware,
> and Phase 6 implements those middleware layers. Consider merging
> into Phase 3 if timeline allows.

Required:
- Add Docker-level sandbox to `ToolRunner` (currently runs all tools as host
  subprocesses)
- Make scope validation a mandatory middleware in `ToolRunner` (currently
  optional per-call wrappers)
- Add runtime governance layer unifying:
  - `LoopBudgetManager` (cycle/depth/LLM limits — already exists)
  - `LlmCostTracker` (dollar cost tracking — already exists)
  - `HardTimeoutSeconds` (wall-clock timeout — already exists)
  - Low-signal detection (NEW — stop if last N tools produced no useful
    findings)
- Add abuse prevention: rate-limit awareness in agent planning

**Files affected:**
- `tools/tool_runner.py` (add mandatory sandbox + scope validation)
- `tools/scope_validator.py` (integrate as mandatory middleware)
- `runtime/governance.py` (NEW — unified cost + budget + timeout +
  low-signal governor)
- `agent/react_agent.py` (consume governance state for planning)

**Testing gate:** `pytest tests/` — all pass. Tool sandbox integration test
  verifies tools execute in isolated namespace. Scope validation test
  verifies out-of-scope targets are blocked with `ScopeViolationError`.

**Migration:** `GOVERNANCE_V2` feature flag. Governance layer wraps existing
  components — fail-open until fully validated.

---

# SECTION 13 — SUCCESS CRITERIA

The refactor is considered successful ONLY when:

## Criterion 1

The `ReActAgent` becomes the sole primary planner — including orchestrating
the full engagement lifecycle, not just scan-phase tool selection.

## Criterion 2

The runtime becomes truly iterative — no batch action dispatch.
`IntelligenceEngine` feeds analysis into the loop; it does not generate
actions independently.

## Criterion 3

All runtime state flows through `EngagementState` — no direct Redis reads,
no orchestrator instance variables, no Celery task memory for runtime state.

## Criterion 4

Retries become replay-safe — every retry replays the original LLM decision,
not a new one.

## Criterion 5

Attack chains become graph-based — `attack_graph.py` gains prerequisite/
downstream- impact modeling. Findings have relationship edges.

## Criterion 6

The deterministic runtime becomes a true fallback-only system — extracted
into `deterministic_runtime.py`, shared executor in `execution_engine.py`.

## Criterion 7

No orchestration component performs semantic reasoning —
`orchestrator_pkg/orchestrator.py` has no mode-selection logic, no strategy
branching, no agent/safety-net orchestration.

## Criterion 8

Scope validation is mandatory middleware in `ToolRunner` — not optional
per-call wrappers that can be bypassed.

---

# FINAL DIRECTIVE

Do NOT add more features before fixing runtime cohesion.

The current repository is architecturally strong but operationally split
between:

```text
workflow engine assumptions
```

and:

```text
autonomous reasoning runtime assumptions
```

The objective of this refactor is to fully transition Argus into:

```text
an agent-first autonomous security runtime
```

with:
- deterministic fallback
- durable cognition
- replay-safe execution
- attack graph reasoning
- transactional runtime state
- scalable orchestration
- safe execution boundaries
