# Argus Implementation and Conformance Plan
## ARTEX graph-backed exploration · PentAGI hierarchical delegation · CAIRN fact-and-intent reasoning

**Prepared:** 22 November 2026  
**Purpose:** A build plan and source-conformance test plan for extending Argus without replacing its existing execution, MCP, scope, evidence, and reporting foundations.

---

## 0. Executive decision

Implement the three architectures as **three layers of one assessment engine**, not as three independent planners:

1. **ARTEX owns the knowledge and exploration model.** It defines the shared asset graph, per-engagement exploration graph, anchors, planner frontier, graph-change feedback loop, and persistent plan scratchpad.
2. **PentAGI owns the work-decomposition model.** Each claimed investigation intent becomes a task with an ordered list of up to 15 subtasks. A primary agent handles the task and delegates individual subtasks to specialists. A refiner revises the remaining subtask list after each terminal subtask result.
3. **CAIRN owns the dispatch protocol and state transitions.** The dispatcher is the control plane and sole writer of durable protocol state. Workers receive one explicit job, return a strict structured result, and never claim work, heartbeat a lease, or write directly to the graph/database.

The resulting hierarchy is:

```text
Argus Engagement
  = CAIRN Project / PentAGI Flow
  |
  +-- Goal(s)                         ARTEX Goal
  |     |
  |     +-- Investigation Intent(s)  ARTEX Intent / CAIRN Intent
  |            |                     Each intent is a PentAGI Task/work package
  |            |
  |            +-- Subtask 1          PentAGI Subtask
  |            +-- Subtask 2          PentAGI Subtask
  |            +-- ...
  |            |
  |            +-- Actions            Tool executions
  |            +-- Result             One CAIRN Fact conclusion, plus any validated findings
  |
  +-- Shared Asset Graph             ARTEX Asset Graph
  +-- Exploration Graph              ARTEX Exploration Graph
```

Multiple independent intents can be claimed by different workers (ARTEX frontier behaviour). **Within one intent/task, subtasks execute in PentAGI order**, one at a time. This preserves ARTEX-style parallelism across independent investigation directions while preserving PentAGI's sequential subtask/refiner lifecycle inside each task.

The CAIRN `reason` contract is the structured interface used by the ARTEX planner: one authoritative planner decides whether to complete a goal, create new intents, or do nothing. The PentAGI Generator creates subtasks *inside a claimed intent*; it does not create a second competing top-level intent queue.

### Non-negotiable control rule

The LLM may propose goals, intents, subtask patches, facts, findings, and actions. It must not grant itself permission to execute them. Argus's trusted dispatcher validates scope, prerequisites, action policy, budgets, and output contracts, then commits state changes. This keeps the three designs compatible with Argus's existing deterministic safety model.

---

## 1. Reference snapshots and fidelity rules

The implementation agent must use pinned repository snapshots, not the latest README text alone. The pins below were resolved on 22 November 2026.

| Project | Repository | Reference commit | Primary source files |
|---|---|---|---|
| ARTEX | [BaaRai/ARTEX](https://github.com/BaaRai/ARTEX) | `94757c5d7e704ac1c095ee99e97d9ac4d9d428c5` | [README](https://github.com/BaaRai/ARTEX/blob/94757c5d7e704ac1c095ee99e97d9ac4d9d428c5/README.md), [agent/planner.go](https://github.com/BaaRai/ARTEX/blob/94757c5d7e704ac1c095ee99e97d9ac4d9d428c5/agent/planner.go), [db/exploration.go](https://github.com/BaaRai/ARTEX/blob/94757c5d7e704ac1c095ee99e97d9ac4d9d428c5/db/exploration.go), [db/assets.go](https://github.com/BaaRai/ARTEX/blob/94757c5d7e704ac1c095ee99e97d9ac4d9d428c5/db/assets.go), [server/engine.go](https://github.com/BaaRai/ARTEX/blob/94757c5d7e704ac1c095ee99e97d9ac4d9d428c5/server/engine.go) |
| PentAGI | [vxcontrol/pentagi](https://github.com/vxcontrol/pentagi) | `cffed9485aa1cca70762cd08a57ac62a80406258` | [Flow execution](https://github.com/vxcontrol/pentagi/blob/cffed9485aa1cca70762cd08a57ac62a80406258/backend/docs/flow_execution.md), [subtask patch](https://github.com/vxcontrol/pentagi/blob/cffed9485aa1cca70762cd08a57ac62a80406258/backend/pkg/providers/subtask_patch.go), [subtask worker](https://github.com/vxcontrol/pentagi/blob/cffed9485aa1cca70762cd08a57ac62a80406258/backend/pkg/controller/subtask.go), [task worker](https://github.com/vxcontrol/pentagi/blob/cffed9485aa1cca70762cd08a57ac62a80406258/backend/pkg/controller/task.go) |
| CAIRN | [oritera/Cairn](https://github.com/oritera/Cairn) | `8e7e0ea67552383851dfcabfba0c4e9c8d007878` | [Dispatcher design](https://github.com/oritera/Cairn/blob/8e7e0ea67552383851dfcabfba0c4e9c8d007878/docs/specs/dispatcher-design.md), [scheduler](https://github.com/oritera/Cairn/blob/8e7e0ea67552383851dfcabfba0c4e9c8d007878/cairn/src/cairn/dispatcher/scheduler/loop.py), [contracts](https://github.com/oritera/Cairn/blob/8e7e0ea67552383851dfcabfba0c4e9c8d007878/cairn/src/cairn/dispatcher/contracts.py), [explore task](https://github.com/oritera/Cairn/blob/8e7e0ea67552383851dfcabfba0c4e9c8d007878/cairn/src/cairn/dispatcher/tasks/explore.py), [reason task](https://github.com/oritera/Cairn/blob/8e7e0ea67552383851dfcabfba0c4e9c8d007878/cairn/src/cairn/dispatcher/tasks/reason.py) |
| Argus baseline | [Olamzkid2005/Argus-](https://github.com/Olamzkid2005/Argus-) | `0e006958927c82d95d293f4e08262df79d95e921` | [README](https://github.com/Olamzkid2005/Argus-/blob/0e006958927c82d95d293f4e08262df79d95e921/README.md), [workflow runner](https://github.com/Olamzkid2005/Argus-/blob/0e006958927c82d95d293f4e08262df79d95e921/Argus-Tui/packages/opencode/src/argus/workflow-runner.ts), [planner executor](https://github.com/Olamzkid2005/Argus-/blob/0e006958927c82d95d293f4e08262df79d95e921/Argus-Tui/packages/opencode/src/argus/planner/executor.ts), [MCP server](https://github.com/Olamzkid2005/Argus-/blob/0e006958927c82d95d293f4e08262df79d95e921/argus-workers/mcp_server.py), [current gaps](https://github.com/Olamzkid2005/Argus-/blob/0e006958927c82d95d293f4e08262df79d95e921/docs/CURRENT-REMAINING-GAPS.md) |

**Important source-lock rule:** If any upstream project moves after these pins, do not silently change the implementation target. Record the new SHA, identify behavioural changes, update the reference specification and conformance fixtures, then approve the change explicitly.

**Meaning of “exactly”:** Reproduce the referenced framework's observable architecture, contracts, lifecycle, ordering, ownership and failure semantics. Do not copy source code, prompts, UI, deployment topology, or branding wholesale. Where the frameworks have incompatible ownership models, use the integration contract in Section 5 and document the adaptation. Review each project's license before copying any code; ARTEX and CAIRN publish AGPL-family licensing terms.

---

## 2. Argus baseline: what already exists and must be reused

The implementation starts from Argus HEAD `0e006958...`, not the earlier 21 November snapshot. That HEAD adds end-to-end banking and AI vulnerability detection; it does not by itself change the orchestration model described below.

### Existing components to preserve

| Existing Argus component | Current responsibility | How the new architecture should use it |
|---|---|---|
| `Argus-Tui/packages/opencode/src/argus/workflow-runner.ts` | Assessment lifecycle, target validation, phase execution, checkpoints, status and reporting orchestration | Evolve behind a feature flag into the trusted dispatcher; do not create a second independent run lifecycle |
| `.../planner/planner.ts` | Capability/phase plan, LLM suggestions and replan rules | Retain as a lower-level capability resolver for a claimed intent/subtask; stop treating it as the top-level source of all investigation directions in V2 |
| `.../planner/executor.ts` | Tool/action execution, hybrid agent loop, action outcome accounting, timeouts and fallback | Reuse as the action executor inside a PentAGI subtask |
| `.../bridge/mcp-client.ts` and `.../bridge/supervisor.ts` | Python worker bridge and process supervision | Extend with typed task/graph RPCs; retain health, restart and degraded-mode semantics |
| `.../engagement/store.ts` and `.../engagement/schema.sql.ts` | Per-engagement SQLite persistence, findings, phases, checkpoints and audit state | Extend with graph, intent, task/subtask and lease tables through migrations |
| `argus-workers/mcp_server.py` | MCP tool server plus `agent_init` / `agent_next` / `agent_observe` hybrid planning protocol | Keep as worker/agent runtime. Make new graph writes go through dispatcher-owned RPCs rather than direct worker DB writes |
| `argus-workers/agent/react_agent.py` | ReAct tool-selection and observation loop | Use as the action-level agent within a delegated task; avoid adding another unconstrained tool loop |
| `argus-workers/agent/session_store.py` | Per-phase ephemeral planning session, action ids, observations and tool history | Keep session state for live execution; durable task/subtask state belongs in the engagement store |
| `argus-workers/agent/swarm.py` and `swarm_memory.py` | Deterministic specialist suite activation, parallel specialists and in-flight signal sharing | Reuse specialist implementations, but put them behind the new primary-agent delegation contract |
| `argus-workers/attack_graph.py` / `attack_graph_db.py` | Finding/vulnerability attack-chain analysis and attack-path risk scoring | Retain for vulnerability chaining. Do not mistake this for ARTEX's asset graph or exploration graph |
| `argus-workers/tools/attack_surface/asset_graph.py` and `tools/attack_paths/asset_graph_builder.py` | In-memory/derived asset graph representations | Treat as existing inputs/builders; replace or wrap them with a canonical, persistent asset graph rather than creating a competing authoritative graph |
| `argus-workers/tools/verification_agent.py` and `tools/verification/` | Reproduction, evidence capture, confidence and finding promotion | Keep as the verifier for findings produced by delegated tasks |
| `Argus-Tui/packages/opencode/src/argus/evidence/` and `browser/` | Artifact capture, HAR parsing, hash integrity and Playwright verifiers | Attach artifacts/evidence references to exploration nodes and findings |

### Known integration constraint

Argus has more than one execution/persistence path: the TUI path uses the per-engagement SQLite store, while the Python service-backed path has PostgreSQL/Redis/Celery components. The current gap register documents a scope/state mismatch between these paths. **Do not implement graph writes by dual-writing SQLite and PostgreSQL or by creating a third state store.**

Before graph implementation, define one `EngagementGraphRepository` contract and select exactly one authoritative backend per engagement. Provide SQLite and PostgreSQL adapters only if both supported execution modes need the feature. All graph and intent mutations must pass through one dispatcher API; adapter parity tests must prove the same transition results on both backends.

### Current Argus features that must not regress

- Scope and target validation, approval gates, egress checks and bounded action identity.
- The structured `agent_next` / `agent_observe` handshake and stable `action_id` validation.
- Capability coverage accounting and the distinction between successful-empty, failed, blocked, skipped and timed-out actions.
- Evidence integrity, finding confidence, browser verification and the seven-question submission gate.
- Per-phase checkpoints, resumability, engagement budgets, audit logs and honest `PARTIAL` / `INTERRUPTED` statuses.
- The ability to run without making Docker mandatory. The new architecture may use the existing sandbox abstraction, but it must not silently weaken execution isolation when Docker is unavailable.

---

## 3. Workstream 1 — ARTEX graph-backed exploration

### 3.1 Behaviour to reproduce

ARTEX has two separate but linked graphs:

**Asset graph (shared across tasks within the relevant company/workspace):** the canonical representation of what exists. The reference model includes `root_domain`, `subdomain`, `ip`, `service`, `app` and `endpoint`. Parent/child relationships and deduplication keys are computed by application code. Agents submit observations; they do not invent canonical IDs.

**Exploration graph (per assessment/task):** the reasoning and progress history. The reference model includes `goal`, `intent`, `fact`, `finding` and `hint` nodes. Typed edges express relationships such as `spawns`, `derived_from`, `yields` and `proves`.

**Anchors:** a many-to-many relationship from an exploration node to one or more asset IDs. This records which asset an intent investigated, which asset a fact describes and which asset a finding affects. Asset coverage is calculated from these anchors and the approved scope.

**Planner/worker loop:** a graph change wakes a debounced planner. The planner reads a compact graph overview, current frontier, coverage and scope; it may dispatch zero or more new intents. Workers claim one intent, execute only that intent, write observations/assets/facts/findings back, and stop. The write-back creates the next planner wake-up. ARTEX's planner keeps a per-task todo scratchpad across wake-ups so a sequential chain is advanced step by step rather than dispatching all dependent steps in parallel. Workers can search other workers' execution traces, but each worker stays confined to its claimed intent.

**Goal rule:** an unmet goal with no open or running intent must not stall. The planner must create at least one new intent. It may emit zero new intents only if the goal is proven or current open/running work is already advancing it and no additional direction is justified.

**Claim rule:** reference ARTEX uses a 15-second heartbeat and a 90-second intent claim TTL. Claims are fenced: once a worker loses its claim, a stale worker must not write results as though it still owns the intent.

### 3.2 Argus data model

Create a canonical graph domain, preferably under:

```text
Argus-Tui/packages/opencode/src/argus/engagement/graph/
  types.ts
  asset-identity.ts
  asset-repository.ts
  exploration-repository.ts
  anchors.ts
  graph-events.ts
  graph-overview.ts
  coverage.ts
  planner.ts
  intent-frontier.ts
```

Extend `engagement/schema.sql.ts` and `engagement/store.ts` with migrations. Suggested logical tables (physical naming can follow existing conventions):

**Asset graph**

- `assets`: `id`, `scope_owner_id`/workspace key, `type`, `canonical_key`, `display_value`, typed metadata, `first_seen_at`, `last_seen_at`.
- `asset_edges`: `source_asset_id`, `relationship`, `target_asset_id`, unique constraint on the triple.
- `asset_observations`: raw value, source tool/action, observed timestamp, parser version and confidence; never store secrets as asset identity.

**Exploration graph**

- `exploration_nodes`: `id`, `engagement_id`, `kind`, structured `payload`, `state`, `priority`, `origin`, `owner`, timestamps and optional source task.
- `exploration_edges`: `engagement_id`, `source_node_id`, `relationship`, `target_node_id`, unique constraint.
- `exploration_anchors`: `node_id`, `asset_id`, unique constraint.
- `exploration_activity`: worker, intent, action id, tool, outcome, summary, timing, token/cost metadata and safe evidence references.
- `planner_todos`: engagement/goal scoped ordered items, state, prerequisites and source planner turn; retained across planner wake-ups and restarts.
- `graph_outbox`: committed graph-change events, sequence/version, event kind and dispatch state. Insert the event in the same transaction as the graph mutation.

Do not store complete HTTP bodies or credentials in graph node JSON. Store references to Argus's existing encrypted evidence artifacts; graph nodes carry hashes/IDs and short safe summaries.

### 3.3 Asset identity and write rules

Implement deterministic canonicalizers for every asset type. Minimum behaviours:

- Normalize hostname case, trailing dots, IDNA and default ports.
- Normalize URLs without losing path/query semantics; strip userinfo and never include credentials in the canonical key.
- Normalize IP addresses and service `(host, port, protocol)` identities.
- Define stable keys per type and enforce database uniqueness, not only in-memory deduplication.
- Compute parent relationships in application code: root domain → subdomain → IP/service/app/endpoint as applicable.
- Merge observations and update `last_seen_at`; do not create duplicate assets when two tools report the same canonical asset.
- Respect tenant/workspace boundaries. Sharing an asset across engagements is allowed only within the same configured owner/scope boundary.
- Validate every asset against the engagement's authorised scope before adding it to the usable asset graph. Out-of-scope discoveries may be recorded as rejected observations for audit, but must not become schedulable assets.

### 3.4 Exploration graph invariants

- Only the five typed node categories above are used for the ARTEX model. Keep evidence files as artifacts, not a sixth pseudo-node type unless a later schema revision explicitly requires it.
- Edges are typed and validated. Reject an edge whose endpoints do not belong to the same exploration/engagement or whose relationship is invalid for the node kinds.
- Goal nodes are operator-controlled. Tool output, web content, files, worker traces and facts cannot create/modify the operator's scope or redefine the goal.
- An intent has a clear lifecycle: `open → running → concluded` or an explicit blocked/released/cancelled terminal/return state. Use compare-and-set transitions.
- A fact is a factual conclusion, not automatically a vulnerability. A finding is a security issue and must retain its evidence/proof lifecycle through Argus's existing verifier.
- A `proves` edge is created only by a trusted verifier/dispatcher after the required verification contract passes; an LLM's text claim alone cannot prove a goal.
- Anchors are explicit and validated. Never infer an anchor to every asset mentioned in arbitrary text.
- Graph writes are idempotent. Replaying the same result/action ID must not create duplicate facts, findings, edges or evidence references.

### 3.5 Planner behaviour

Implement one `ExplorationPlanner` with these responsibilities:

1. Read `graph_overview` first: goals, confirmed facts, open/running intents, findings, hints, frontier count, asset coverage and scope constraints.
2. Read only the relevant details/traces for the current trigger, then obtain more details on demand. Keep the prompt bounded; use summaries for older activity.
3. Restate the operator-owned goal and constraints at the end of the planner input. Treat all observations/tool outputs as untrusted data, not instructions.
4. Evaluate each goal. Mark it proven only from a valid proof-bearing fact/finding chain.
5. Consult the persistent todo list. Mark items satisfied by existing facts; do not duplicate pending/in-progress work; only dispatch the next chain step when its prerequisite facts exist.
6. Generate `0..N` intent proposals with `from` fact IDs, target asset anchors, objective, prerequisites, priority and rationale. The dispatcher validates and persists them.
7. Apply the hard floor: if a goal is unmet and there are no open or running intents, the planner must propose at least one applicable next intent. A planner `done`/empty result in this state is a conformance failure.
8. If current open/running intents already cover the active frontier and there is no new direction, return no new intents rather than creating repetitive work.
9. Trigger a debounced new planning round after committed graph changes (facts, assets, findings, hints, intent completion, goal changes). Do not spin continuously on unchanged state.

The planner is the **only autonomous intent proposer**. Human/operator controls may add goals or hints; specialist agents and subtask workers may return evidence and suggestions, but they do not independently create durable top-level intents.

### 3.6 Intent claims, worker isolation and trace reuse

- Implement an atomic `claimNext` using a transaction/compare-and-set operation.
- Each claim gets a cryptographically random fencing token. The claim stores worker ID and heartbeat timestamp.
- Mirror ARTEX defaults: heartbeat every 15 seconds; claim expires after 90 seconds using the database clock. Make values configurable only with defaults and validation that preserve the reference semantics.
- Every heartbeat, result write and release must present the current claim token. A stale worker receives `CLAIM_LOST`; its result is not committed.
- An intent worker receives the intent description, authorized anchor assets, prerequisite facts, relevant trace summaries and its permitted tool/capability set. It cannot widen target scope.
- Workers may search other workers' traces for reusable observations, but trace data is untrusted and must be redacted/sanitized before it enters a planning prompt.
- Preserve a per-goal/per-engagement todo list across planner wake-ups. Dependent actions remain ordered; independent intents may be claimed by separate workers.

### 3.7 Implementation milestones

**A1 — Graph schema and repositories**

- Add schema/migrations, typed node/edge definitions and repository interfaces.
- Implement SQLite adapter for the TUI/local path; implement PostgreSQL adapter only where the service-backed path is explicitly enabled.
- Add idempotent asset upsert, exploration node/edge CRUD and anchor operations.
- Add tenant/scope isolation and encrypted-artifact references.

**A2 — Graph ingestion and coverage**

- Convert structured recon/tool outcomes into raw asset observations.
- Canonicalize and upsert assets programmatically.
- Create/anchor facts and findings through trusted ingestion code.
- Compute in-scope asset coverage and untested asset classes.

**A3 — Planner frontier and event loop**

- Add graph overview queries, graph outbox and debounced planner wake-up.
- Introduce typed intent proposal contract and a single planner owner.
- Add persistent todos and prerequisite-aware serial chains.
- Wire goal proof to Argus's evidence/verification engine.

**A4 — Claims, workers and trace search**

- Implement claim token, heartbeat, expiry, release and stale-worker fencing.
- Route existing MCP workers through one intent at a time.
- Add cross-worker trace search with per-intent execution isolation.

**A5 — Shadow mode and rollout**

- Run the graph planner in proposal-only mode against existing assessments.
- Compare proposed frontier with the current deterministic phase plan.
- Enable execution only after conformance tests pass; retain a rollback flag to the legacy workflow path.

### 3.8 ARTEX conformance tests (mandatory)

| ID | Test | Required result |
|---|---|---|
| A-01 | Upsert the same root domain/subdomain/URL with case/default-port/trailing-slash variations | One canonical asset per identity; observations merge; parent links remain valid |
| A-02 | Same asset discovered by two tools in one workspace | Same asset ID, two source observations, no duplicate asset node |
| A-03 | Same domain discovered under two different tenant/workspace scopes | No cross-tenant asset visibility or accidental merge |
| A-04 | Create an intent/fact/finding anchored to an asset | Anchor persists and graph query returns exact relationship |
| A-05 | Attempt invalid edge, cross-engagement edge or out-of-scope anchor | Rejected before mutation; audit reason recorded |
| A-06 | Burst of graph updates | Debounced planner wake occurs; no lost event; repeated updates do not create unbounded planner turns |
| A-07 | Unmet goal, no open/running intents | Planner must produce at least one valid intent or return a hard planner error; it may not report completion |
| A-08 | Goal proven by verified evidence | Goal is marked complete; subsequent wake produces no new intent for that goal |
| A-09 | Open/running intent already covers the only known direction | No duplicate intent is created absent new evidence/direction |
| A-10 | Three-step dependent investigation | Step 2 cannot dispatch before fact from step 1; step 3 cannot dispatch before fact from step 2 |
| A-11 | Worker claim heartbeat and expiry | Live claim is not stolen; stale claim may be reclaimed after 90 seconds; heartbeat cadence defaults to 15 seconds |
| A-12 | Old worker submits after claim takeover | Fencing token rejects write; no fact/finding/edge is committed |
| A-13 | Worker A discovers endpoint, Worker B later needs it | B can retrieve the trace/structured fact without repeating A's action |
| A-14 | Prompt injection appears in HTTP response or worker trace | It is treated as data; it cannot add goals, change scope, prove a goal or authorize a new target |
| A-15 | Process restarts after planner todo is written | Todo state and dependency order survive restart |
| A-16 | Same action/result is delivered twice | Idempotent write; one logical graph update |

---

## 4. Workstream 2 — PentAGI hierarchical delegation

### 4.1 Behaviour to reproduce

PentAGI models work as:

- **Flow:** persistent top-level engagement/session.
- **Task:** an objective within the Flow.
- **Subtask:** an ordered, automatically decomposed step for a Task.
- **Action:** an individual tool operation, command, search or analysis.

Its control roles are distinct:

- **FlowWorker:** manages the flow lifecycle and task coordination.
- **TaskWorker:** owns task state, subtask generation, ordered execution and refinement.
- **SubtaskWorker:** executes one subtask and owns its status/message chain.
- **Primary Agent:** handles a subtask and delegates to specialists when required.
- **Generator Agent:** decomposes a task into an ordered subtask list (reference cap: 15).
- **Refiner Agent:** reviews completed and remaining subtasks after each subtask completion; can add, remove, modify and reorder planned subtasks.
- **Specialist Agents:** Pentester, Coder, Installer, Searcher, Adviser, Memorist, Enricher and Reporter roles as appropriate.
- **Reflector Agent:** repairs unstructured/invalid agent output; the reference flow documents a maximum of three correction attempts.
- **Reporter Agent:** produces the final task report after the task's subtask work is complete.
- **Memorist Agent:** stores and retrieves useful long-term execution knowledge.

The reference subtask lifecycle persists status and message-chain state. A subtask can be created, running, waiting, finished or failed. `done` is a completion barrier; `ask` pauses for operator input. The task runs its ordered subtask list and invokes the Refiner after each terminal subtask result. A new/refined plan must preserve the identity and history of existing subtasks where possible.

### 4.2 Argus mapping

Use this mapping to avoid a second competing hierarchy:

- Argus Engagement = Flow.
- An ARTEX/CAIRN Investigation Intent = one PentAGI-style Task/work package.
- The Generator's ordered plan = that Task's Subtask list (maximum 15 active planned subtasks by default).
- Each tool call executed by Argus's existing executor = an Action.
- ReAct remains the action-level execution loop inside the Primary Agent; it is not promoted into a second task planner.

Independent intents/tasks can run concurrently under the ARTEX frontier. Within one task, execute subtasks sequentially in list order, matching PentAGI's task execution model. Do not parallelize sibling subtasks within the same task unless a future explicit mode is added and separately tested.

### 4.3 Suggested code layout

```text
argus-workers/agent/delegation/
  models.py              # Flow/Task/Subtask/Action and status contracts
  generator.py           # ordered subtask generation, max 15
  primary.py             # primary agent and specialist delegation
  refiner.py             # post-subtask patch generation
  patch.py               # deterministic patch validation/application
  reflector.py           # malformed-output recovery, max 3
  reporter.py            # task-level report assembly
  memorist.py            # long-term memory adapter
  registry.py            # specialist roles and capabilities
```

The durable copy of Flow/Task/Subtask status belongs in the Argus engagement repository, not in the ephemeral Python `AgentSessionStore`. The session store remains a short-lived execution cache. Use bridge methods to create/resume a task and to stream structured action/progress results; the dispatcher persists them.

### 4.4 Task and subtask data contracts

**Task**

```text
id, engagement_id, intent_id, objective, status,
created_at, updated_at, generator_version, task_context_ref
```

**Subtask**

```text
id, task_id, ordinal, title, description, status,
created_at, updated_at, started_at, finished_at,
result_ref, message_chain_ref, retry_count, last_error
```

**Action**

```text
id, subtask_id, action_id, tool, canonical_arguments,
source_agent, reasoning_ref, outcome, started_at, finished_at,
result_ref, evidence_refs
```

Statuses must be explicit and monotonic where applicable:

- `CREATED → RUNNING → FINISHED`
- `RUNNING → WAITING` when the worker needs operator input
- `WAITING → RUNNING` after accepted input
- `RUNNING → FAILED` after terminal failure

A failed or skipped subtask must never be silently represented as finished. A task cannot be reported as fully completed if required subtasks are still running, waiting, failed, or omitted without a recorded reason.

### 4.5 Generator contract

- Input: one authorized intent/task objective, the relevant asset/fact graph snapshot, scope, task-specific capabilities, known findings and constraints.
- Output: an ordered array of 1–15 `{title, description}` subtask objects, each with an optional dependency list and expected completion condition.
- The Generator does not run tools and cannot write to the database.
- The dispatcher validates the output, assigns stable subtask IDs and persists it before execution.
- If the objective is genuinely atomic, a one-item plan is valid. Empty plan is valid only when the task has already been proven complete or is explicitly rejected as unsupported; otherwise it is a generation failure.
- The task planner must not duplicate an existing active/finished subtask simply because the LLM rephrased it. Deduplicate using stable task-local identity plus semantic review, not just title string equality.

### 4.6 Primary agent and specialist delegation

- The Primary Agent receives exactly one subtask description, its dependencies, relevant facts/assets, the authorized target set and the allowed specialist/tool registry.
- It may call a specialist agent through a typed delegation interface. The specialist gets a bounded payload and returns a structured result; it does not mutate the task or graph directly.
- Specialist activation should be capability/need based. Reuse Argus's existing specialist implementations and `swarm.py` where possible; do not launch the whole swarm for every subtask.
- Specialist outputs are merged by the Primary Agent, with source provenance retained. Conflicting findings must be passed to the verifier/correlation layer rather than arbitrarily choosing one.
- All actions still go through Argus's existing tool registry, scope guard, approval and execution layer.

### 4.7 Refiner contract and patch semantics

After each subtask reaches a terminal state, invoke the Refiner with:

- the complete current ordered subtask list and statuses;
- the just-completed subtask result and associated facts/findings;
- remaining open subtasks;
- graph changes since the previous refinement;
- the original task goal and scope.

The Refiner returns an ordered list of delta operations, not a replacement free-text plan:

- `ADD`: required title/description and insertion point (`after_id` or beginning).
- `REMOVE`: existing non-running planned subtask ID.
- `MODIFY`: existing subtask ID plus changed title and/or description.
- `REORDER`: existing subtask ID plus insertion point.

Apply operations in order using deterministic code. Validate every referenced ID. Assign new IDs only after validation. Preserve completed subtask result/history; do not delete or rewrite completed evidence. A running subtask cannot be removed/reordered while execution is in flight. Enforce the maximum of 15 active planned subtasks after applying a patch; reject a patch that exceeds the limit or violates references. Log the Refiner's rationale and the exact patch applied.

The Refiner may leave the remaining plan unchanged. It must not change the parent task's goal, the engagement scope, or the authorization policy.

### 4.8 Reflector, waiting and task completion

- If an agent returns unstructured output where a structured tool call/result is required, run the Reflector correction loop up to three times, preserving the same subtask/session context.
- If the output is still invalid after three corrections, mark the subtask `FAILED` or `WAITING` with an explicit reason; do not fabricate a successful result.
- Provide an explicit `ASK_USER`/`WAITING` result when credentials, role mapping or operator input is required. Persist the question and resume the same task/message chain when input arrives.
- `DONE` can be accepted only when the subtask completion predicate is satisfied and required results have been persisted.
- After all required subtasks are terminal, invoke the Reporter to assemble the task-level report from persisted results and evidence references. Reporting must not generate new findings.
- Use the Memorist role to store/retrieve reusable, redacted knowledge across tasks/engagements. Keep tenant boundaries; do not persist secrets, raw session tokens or target-private data without explicit policy.

### 4.9 Restart and recovery semantics

- Persist subtask order, status, task context, message-chain reference and action outcomes.
- On restart, reconcile a stale `RUNNING` subtask. PentAGI reloads a still-running subtask as created and reuses its persisted agent chain; Argus should reproduce the safe equivalent: mark the interrupted subtask resumable, reload the same message chain, and re-enter it under the original scope/budget.
- Before replaying an action, consult Argus's action-signature ledger and execution log. Reuse a completed result when the action is idempotent and still valid; require a fresh authorized attempt where replay safety is uncertain.
- A `WAITING` subtask remains waiting until valid operator input is recorded.
- A failed subtask remains failed unless an explicit retry/refinement decision creates a new attempt record.

### 4.10 Implementation milestones

**P1 — Persistent hierarchy**

- Add task/subtask/action models, schema and repository methods.
- Tie every Task to one intent and every task to an engagement.
- Add state transitions, status validation and resumability.

**P2 — Generator and sequential TaskWorker**

- Implement Generator schema/output validation and max-15 cap.
- Persist ordered subtasks before execution.
- Execute exactly one subtask at a time within a task.

**P3 — Primary Agent and specialist delegation**

- Use existing ReAct/action executor as the Primary Agent's tool/action layer.
- Add typed specialist delegation adapters; reuse current specialists rather than duplicate them.
- Record delegation provenance and merge structured outputs.

**P4 — Refiner and patch engine**

- Implement ADD/REMOVE/MODIFY/REORDER operation schema and deterministic patch application.
- Run Refiner after every terminal subtask result.
- Preserve completed IDs/results and enforce 15-item cap.

**P5 — Reflector, waiting, reporting and memory**

- Add 3-attempt reflection limit, ASK/WAITING resume, Reporter and Memorist adapters.
- Wire all outputs to Argus evidence and finding verification.

### 4.11 PentAGI conformance tests (mandatory)

| ID | Test | Required result |
|---|---|---|
| P-01 | Create an engagement, task and subtasks | Flow/Task/Subtask/Action hierarchy and foreign-key ownership are correct |
| P-02 | Generator returns 16 subtasks | Dispatcher rejects/clamps according to explicit policy; no more than 15 are persisted |
| P-03 | Generator returns unordered dependencies | Dispatcher validates and stores a deterministic valid order; dependency violations are rejected |
| P-04 | Execute task with 3 subtasks | Subtask 2 does not start before subtask 1 is terminal; subtask 3 does not start before subtask 2 |
| P-05 | Two independent intent tasks exist | They may execute concurrently under ARTEX worker limits; each task remains sequential internally |
| P-06 | Complete a subtask | Refiner is invoked with completed result, remaining tasks and current graph/facts |
| P-07 | Apply every patch type | ADD/REMOVE/MODIFY/REORDER matches the reference delta semantics and insertion ordering |
| P-08 | Patch references unknown ID | Entire patch is rejected or normalized according to a documented deterministic policy; no partial corruption |
| P-09 | Refiner attempts to edit completed evidence | Rejected; completed subtask result/history remains immutable |
| P-10 | Patch creates 16 active subtasks | Rejected; persisted plan remains unchanged |
| P-11 | Primary Agent delegates to specialist | Specialist receives bounded context; result/provenance returns to Primary Agent; no direct DB mutation |
| P-12 | Agent emits invalid/unstructured output | Reflector gets at most 3 attempts; failure is explicit and is not reported as completion |
| P-13 | Agent requests operator input | Subtask becomes WAITING; subsequent input resumes same task/context |
| P-14 | Process dies while subtask RUNNING | Restart reconciles it to resumable state; prior result/evidence remains; duplicate actions are not blindly repeated |
| P-15 | All required subtasks finish | Reporter runs once and builds report only from persisted findings/evidence |
| P-16 | Memorist retrieves prior engagement knowledge | Only permitted tenant-scoped, redacted context is returned |
| P-17 | A failed/blocked/skipped subtask exists | Task cannot be marked fully successful without an explicit resolution/accepted skip reason |

---

## 5. Workstream 3 — CAIRN fact-and-intent reasoning

### 5.1 Behaviour to reproduce

CAIRN separates three worker task types and makes the Dispatcher the control plane:

- The server/database is the protocol source of truth.
- The Dispatcher reads current graph state, chooses a task type and worker, manages the process/session/lease and writes validated results back.
- The worker/agent receives one explicit prompt and returns structured JSON. It does not claim intents, heartbeat them or call the server API itself.
- The Dispatcher handles cancellation, timeouts, health checks, result parsing, conclude fallback, release and cleanup.

Argus should reproduce that ownership model. The TypeScript `WorkflowRunner`/engagement control plane (or a single equivalent service selected for the deployment) owns durable state transitions. Python agents return typed proposals/results through MCP. They do not write directly to the graph store.

### 5.2 The three task types

#### A. `bootstrap`

**Eligibility:** a pristine engagement with exactly the initial `origin` and `goal` facts and no ordinary intents (or only the reserved bootstrap intent); bootstrap is enabled and a configured worker supports it.

**Input:** origin, goal and hints. The bootstrap prompt is deliberately not a full graph snapshot.

**Execute output contract:** both a Fact and a Complete result are mandatory:

```json
{
  "accepted": true,
  "data": {
    "fact": { "description": "..." },
    "complete": { "description": "..." }
  }
}
```

A valid execute result writes the Fact and then completes the goal. A `bootstrap_conclude` fallback is different: it may write a Fact only; it must not complete the goal. If execute times out or output is malformed, the same worker session may run the conclude prompt if the driver supports it. If both stages fail, release the reserved intent; do not fabricate a Fact or mark the goal complete.

#### B. `reason`

**Input:** graph snapshot, explicit valid fact IDs, open intents and hints.

**Allowed result forms:**

- `complete`: exactly one completion object with `from` fact IDs and description.
- `intents`: one or more intent objects with `from` fact IDs and description, bounded by `max_intents`.
- `noop`: no mutation when work is already active and no new direction is warranted.

`complete` and `intents` cannot coexist. If the open-intent list is empty and the goal is not complete, an empty/no-op result is invalid: the reasoner must propose at least one intent. Every referenced fact ID must exist in the current engagement; goal IDs are not accepted as fact sources. The LLM returns JSON; the dispatcher validates it and performs the graph/database write.

**Reason scheduling:** preserve CAIRN's checkpoint rules:

- Run once on initial state when there is no prior reason checkpoint.
- Re-run when fact count increases.
- Re-run when hint count increases.
- Re-run when the project transitions from one or more open/running intents to zero open/running intents.
- Do not re-run solely because an explore attempt failed/released while the same intent remains open.

Use a project/engagement-level reason lease so at most one reason task runs for a given engagement at a time.

#### C. `explore`

**Input:** one claimed intent, a graph snapshot and the exact intent description/ID.

**Output:** exactly one fact conclusion description. The worker explores only that claimed intent; if the task needs several tools, it can do so within its bounded PentAGI task/subtask hierarchy. When it is finished, the dispatcher writes one conclusion Fact and connects it to the intent through the appropriate `yields`/`derived_from` relationship.

**Failure handling:**

- If the worker returns valid output, validate and conclude the intent.
- If it times out or returns malformed JSON, the same worker session may run `explore_conclude` if supported and if the claim is still live.
- If the worker is rejected, unsupported, crashes without a usable session, loses its lease or is cancelled, release/stop it; do not write a fabricated Fact.
- Do not run conclude fallback after cancellation or claim loss.

### 5.3 Strict contracts

Use JSON Schema or typed validators for each task type. The validator must reject unknown keys where the reference contract does, missing fields, empty descriptions, wrong primitive types, invalid fact IDs, and conflicting result forms.

**Reason**

```text
accepted=false                         -> REJECTED; no graph write
accepted=true, data.complete           -> COMPLETE; no intents allowed
accepted=true, data.intents=[...]       -> create 1..max_intents intents
accepted=true, data={}                  -> NOOP only when open intents exist
open_intents empty + no complete/intent -> INVALID; must create an intent
```

For compatibility, CAIRN's current parser accepts the singular `intent` spelling as a legacy alias; Argus should emit `intents` only, and may accept singular only behind an explicit compatibility switch with a deprecation log.

**Bootstrap execute:** exact `fact.description` plus `complete.description` required.  
**Bootstrap conclude:** `fact.description` required; no completion write.  
**Explore:** one non-empty `description` required; it becomes one conclusion Fact.

### 5.4 Dispatcher scheduling and worker selection

Implement a task registry with supported task types (`bootstrap`, `reason`, `explore`), worker health, max concurrency, priority and current running count.

Worker selection must:

1. Filter by support for the requested task type.
2. Filter out workers at `max_running`.
3. Filter out temporarily unhealthy workers.
4. Filter out workers temporarily rejected for the same task/project where applicable.
5. Sort by configured priority, then current running count, then tie-break consistently (CAIRN randomizes exact ties; tests must inject a deterministic random source).
6. Claim the intent/reason lease before starting a worker process.

Respect global worker limits and per-engagement worker limits. Prefer already-running engagement workers before starting new engagement environments, while retaining a fair rotating order so one long engagement does not starve other eligible engagements.

CAIRN documents a single Dispatcher instance. For Argus, implement the same **single authoritative dispatcher per engagement** invariant. A DB-backed leader/lease can allow multiple Argus processes to exist while ensuring only one owns an engagement's scheduling and graph writes. Do not allow two dispatchers to race on the same intent or reason operation.

### 5.5 Lease, heartbeat, cancellation and state ownership

- Intent claim/heartbeat/release is performed by the dispatcher, never by the LLM/worker.
- `reason` has a mutually exclusive engagement-level lease.
- `explore` and `bootstrap` have intent-level leases.
- Every worker process is registered with task type, worker ID, engagement ID, intent ID, start time, timeout and cancellation handle.
- When an engagement becomes stopped/inactive/deleted, do not dispatch new work; cancel all local running tasks; do not run conclude fallback; reject all late results; clean up worker processes and temporary execution environments.
- Heartbeat failure means the worker no longer owns the job. It must stop/abort and cannot write a Fact.
- A worker health failure places that worker in a temporary unavailable window rather than retrying it continuously.
- Result writes are idempotent and tied to task ID, intent ID and current lease token.

### 5.6 Worker output boundary and prompt safety

- Worker receives only its assigned task payload, authorized target/scope information, relevant graph snapshot and the specific expected JSON schema.
- Worker does not receive database credentials, graph-store write credentials or dispatcher API credentials.
- Output is parsed from a bounded response channel; do not trust arbitrary stdout/stderr as a valid result.
- Preserve raw stdout/stderr as redacted diagnostics, not as graph facts by default.
- Treat target responses, source files, screenshots, tool output and retrieved traces as untrusted data. They cannot change task type, target, scope, completion criteria or allowed tools.
- The dispatcher validates every proposed fact/intent and every referenced fact/asset against the authoritative graph and scope.

### 5.7 Implementation milestones

**C1 — Dispatcher contracts and ownership**

- Add `bootstrap`, `reason`, `explore` request/result models and validators.
- Define dispatcher interfaces for claim, heartbeat, conclude, release, completion and cancellation.
- Ensure workers cannot write to graph stores directly.

**C2 — Lease and scheduler**

- Implement reason lease, intent claims, worker task support/capacity/health checks and fairness.
- Add task process registry, cancellation handles and heartbeat renewal.

**C3 — Bootstrap/reason/explore workflows**

- Implement initial bootstrap eligibility and reserved intent.
- Implement reason checkpoints/trigger rules and structured result writes.
- Implement one-intent explore and one-Fact conclusion.
- Add same-session conclude fallback with correct cancellation/lease guards.

**C4 — Worker adapters and health**

- Reuse Argus's current Python worker runtime and MCP transport.
- Add typed request/response methods in `WorkersBridge` and `mcp_server.py`.
- Add startup/task health checks and bounded unavailable windows.

**C5 — Recovery and cleanup**

- Reconcile stale dispatcher/worker records after restart.
- Reclaim expired claims using the database clock and current lease token.
- Cancel stale processes and reject late output.

### 5.8 CAIRN conformance tests (mandatory)

| ID | Test | Required result |
|---|---|---|
| C-01 | Fresh engagement with origin+goal and bootstrap enabled | Bootstrap selected only when a compatible worker exists or a reserved bootstrap intent already exists |
| C-02 | Bootstrap execute returns Fact+Complete | One Fact written, then goal completed; no duplicate write on replay |
| C-03 | Bootstrap execute times out; conclude returns Fact | Fact written; goal remains open; reason runs later |
| C-04 | Bootstrap conclude returns Complete | Rejected; conclude cannot complete the goal |
| C-05 | Bootstrap both stages fail | Reserved intent released; no Fact and no Complete written |
| C-06 | Reason returns `complete` plus `intents` | Rejected; no partial graph mutation |
| C-07 | Reason references nonexistent fact ID | Rejected; no intent/completion written |
| C-08 | Reason returns empty data while no open intents exist | Rejected; planner must propose at least one intent if goal remains unresolved |
| C-09 | Reason returns more than `max_intents` | Bounded to configured maximum exactly as the reference contract; record truncation/validation outcome |
| C-10 | Reason runs twice concurrently for one engagement | Exactly one obtains the reason lease |
| C-11 | Reason task failure with no graph change | No immediate repeat reason loop; next trigger follows checkpoint rules |
| C-12 | Fact count or hint count increases | One new reason trigger is eligible |
| C-13 | Open intents transition from positive count to zero | Reason becomes eligible |
| C-14 | Explore claims one intent | It receives only that intent and one lease; no second intent is attached |
| C-15 | Explore valid result | Exactly one conclusion Fact is written and linked to that intent |
| C-16 | Explore malformed output/timeout; conclude succeeds | Same session used; one Fact written; no duplicate conclusion |
| C-17 | Explore cancellation or lease loss before conclude | Conclude fallback does not run; no Fact is written |
| C-18 | Worker attempts direct graph/API/database write | No credentials/path available; operation denied or impossible |
| C-19 | Engagement switches to stopped/inactive during execution | No new tasks; current task cancelled; late result rejected; no conclude fallback |
| C-20 | Worker exceeds max_running or becomes unhealthy | Scheduler selects another eligible worker or waits; does not overrun limits |
| C-21 | Two dispatcher processes target same engagement | Only one obtains scheduling/leader authority |
| C-22 | Worker returns valid JSON with extra/invalid fields | Contract validator rejects or handles only the explicitly allowed compatibility fields |

---

## 6. Integrated execution contract

This section is the shared contract that prevents the three workstreams from becoming separate products inside Argus.

### 6.1 One authoritative state writer

The dispatcher is the only component allowed to commit durable graph/task/intent state transitions. This is the CAIRN ownership rule.

The agents may return structured proposals and evidence. The dispatcher validates and commits them into ARTEX's graphs. This preserves ARTEX's write-back behaviour while using CAIRN's safer API/state ownership boundary.

### 6.2 One top-level planner

The ARTEX-style `ExplorationPlanner` is the only autonomous generator of durable intent proposals. It uses CAIRN's `reason` output contract. The PentAGI Generator is not a second top-level intent planner; it decomposes one already-claimed intent/task into ordered subtasks.

The PentAGI Refiner may patch only that task's remaining subtasks. It cannot create an independent engagement-level intent, change scope or prove a goal.

### 6.3 Full lifecycle

```text
1. Engagement created
   - Persist operator origin and goal.
   - Validate target/scope and initialize budget.

2. CAIRN bootstrap (only if eligible/configured)
   - Worker tries the initial objective.
   - Fact + Complete only if goal is actually achieved.
   - Otherwise conclude may return Fact only.

3. ARTEX planner / CAIRN reason
   - Read graph overview, facts, hints, anchors, open intents and coverage.
   - Return complete, new intent proposals or no-op under CAIRN contract.
   - Dispatcher validates and persists intents in ARTEX exploration graph.

4. ARTEX frontier scheduler / CAIRN explore
   - Claim one intent with a lease.
   - Resolve its anchored assets and prerequisites.

5. PentAGI task hierarchy
   - Create one Task for that intent.
   - Generator creates 1..15 ordered subtasks.
   - Primary Agent runs each subtask sequentially.
   - Specialist Agents handle bounded delegated work.
   - Refiner patches remaining subtasks after each terminal subtask.
   - Reflector corrects malformed outputs up to 3 times.
   - Reporter aggregates the task result.

6. CAIRN explore conclusion / ARTEX graph write-back
   - Return one Fact conclusion for the claimed intent.
   - Dispatcher validates and commits Fact, Assets, Findings, edges and anchors.
   - Finding verification remains Argus's proof/verification pipeline.

7. Graph-change event
   - Debounced wake-up.
   - Update todo state and coverage.
   - If new direction or reason trigger exists, plan again.
   - Otherwise wait for active work or finish only when goal proof is satisfied.
```

### 6.4 Critical distinctions

- A **Fact** is not automatically a **Finding**.
- A **Finding** is not automatically a **Verified Finding**.
- A **Tool success** is not automatically a completed **Subtask**.
- A **completed Subtask** is not automatically a completed **Intent**.
- A **completed Intent** is not automatically a completed **Goal**.
- A **model response saying “done”** is not proof of goal completion.

Each transition requires its own structured evidence and validator.

### 6.5 Suggested MCP/bridge contract additions

Keep existing `agent_init`, `agent_next` and `agent_observe` for the action-level ReAct loop. Add a separate typed task protocol rather than changing their meaning:

- `task_bootstrap(request) → BootstrapResult`
- `task_reason(request) → ReasonResult`
- `task_explore(request) → ExploreResult`
- `task_generate_subtasks(request) → SubtaskPlan`
- `task_refine_subtasks(request) → SubtaskPatch`
- `task_progress(task_id, subtask_id, event)` for progress only (not durable graph writes)
- `task_cancel(task_id, reason)`
- `graph_snapshot(engagement_id, version) → read-only GraphOverview`

The bridge must validate engagement IDs, intent IDs, task IDs, action IDs, schema versions and payload size. All mutations are submitted to dispatcher methods, not generic unrestricted SQL/graph RPCs.

### 6.6 Suggested feature flags

- `ARGUS_ORCHESTRATION_V2=off|shadow|on`
- `ARGUS_GRAPH_EXPLORATION=off|shadow|on`
- `ARGUS_HIERARCHICAL_DELEGATION=off|shadow|on`
- `ARGUS_CAIRN_PROTOCOL=off|shadow|on`

Defaults remain `off` until conformance gates pass. `shadow` can build graphs and proposals without dispatching new work. Do not enable multiple flags independently if their contracts are not ready; the integrated V2 path should be switched on only when the full state/ownership contract is satisfied.

---

## 7. AI implementation agent: required verification protocol

The coding agent must run this protocol after each workstream and again after integration. It must not mark a workstream complete because a class/file exists or because a unit test is mocked.

### 7.1 Before coding

1. Checkout or inspect Argus commit `0e006958927c82d95d293f4e08262df79d95e921` (or the explicitly approved descendant commit).
2. Read every pinned upstream file listed in Section 1, including implementation and tests where available. Do not rely on README summaries alone.
3. Write a concise `reference-behaviour.md` for each workstream. Every requirement must cite an upstream path and symbol/function (plus line range from the pinned commit).
4. Read the current Argus path and tests for every intended integration point. Confirm whether the work already exists before adding a duplicate.
5. Produce a file-level implementation map and migration/rollback plan. Do not edit code until the design identifies the authoritative state store and writer.
6. Capture baseline results from the repository's existing test targets. If a baseline test fails, record it before changes; do not attribute it to the new work.

### 7.2 During implementation

For each requirement ID (`A-*`, `P-*`, `C-*`):

1. Add a deterministic test first where practical.
2. Implement the smallest component that satisfies the requirement.
3. Trace the actual runtime call path from the public command to durable state write. A unit test of an unused helper is not sufficient.
4. Verify both success and failure paths, including timeout, cancellation, LLM unavailable, malformed JSON, stale lease, missing tool and database write failure.
5. Verify that scope, credentials, budgets, approvals and evidence controls remain enforced at the final execution boundary.
6. Run tests for the changed module and its callers.
7. Update the conformance ledger with implementation path, test path, command, result and evidence artifact.

### 7.3 After each workstream

The AI must produce a conformance report with one row per requirement:

| Field | Required content |
|---|---|
| Requirement ID | e.g. `A-11` |
| Reference behaviour | Short exact statement |
| Upstream proof | Pinned repository path, symbol and line range |
| Argus implementation | Exact path, symbol and line range |
| Test proof | Test file/name and command |
| Runtime proof | Integration/live-lab trace or explicit `NOT RUN` |
| Result | `PASS`, `PARTIAL`, `FAIL`, `NOT VERIFIED` |
| Deviation | Exact difference and reason, or `none` |

Rules:
- `PASS` requires both code-path inspection and a passing automated test. State-machine/worker behaviours also require an integration test.
- `PARTIAL` means some component exists but the complete runtime path is not proven.
- `NOT VERIFIED` means no credible test/evidence was run.
- Never infer `PASS` from a README, TODO, class name, test double or mocked call alone.
- Never report a test count unless the command actually ran in the current checkout and its exit code was observed.
- If a source behaviour is intentionally adapted, record it as a deviation; do not label it exact parity.

### 7.4 Minimum automated verification commands

Run from the repository root, adjusting only for the repository's documented virtual environment:

```bash
# Static integrity and whitespace
 git diff --check
 git status --short

# Existing aggregate validation targets
 make typecheck-v5
 make test-v5

# Python lint
 cd argus-workers && ruff check .
```

Add and run focused tests for every workstream. Example new files (names are illustrative but should be similarly explicit):

```text
argus-workers/tests/test_exploration_graph_repository.py
argus-workers/tests/test_asset_identity.py
argus-workers/tests/test_graph_planner_frontier.py
argus-workers/tests/test_intent_claim_fencing.py
argus-workers/tests/test_hierarchical_generator.py
argus-workers/tests/test_subtask_refiner_patch.py
argus-workers/tests/test_primary_specialist_delegation.py
argus-workers/tests/test_reflector_contract.py
argus-workers/tests/test_cairn_task_contracts.py
argus-workers/tests/test_cairn_dispatcher_scheduler.py
argus-workers/tests/test_cairn_lease_and_cancellation.py
```

For TypeScript-owned store/dispatcher code, add focused Bun tests under `Argus-Tui/packages/opencode/test/argus/` and run them from `Argus-Tui/packages/opencode` with `bun test <test-file>`.

### 7.5 Required integration scenarios

Use an isolated local vulnerable fixture and deterministic fake tools/LLM for most tests. Use only a specifically authorized lab for live network tests.

**Scenario 1 — Happy-path graph exploration**

- Start a fresh authorized engagement with origin and goal.
- Bootstrap is eligible and returns a valid fact but not a valid completion; verify goal remains open.
- Reason sees no active intents and creates two valid intents from existing fact IDs.
- Scheduler claims one intent; its PentAGI Generator creates an ordered subtask plan.
- Primary Agent executes the subtasks sequentially, delegates one to a specialist, and Refiner adjusts the remaining plan after a discovery.
- Explore concludes with exactly one Fact; a validated vulnerability is separately recorded as a Finding with proof/evidence.
- Asset/exploration graphs, anchors, edges, todo list and task states persist.
- Graph change triggers a new reason round; the planner proposes a justified next intent or proves the goal from verifier-backed evidence.

**Scenario 2 — No-stall and no-duplicate behaviour**

- Leave a goal unresolved with zero open/running intents: planner must create a valid intent.
- Leave one applicable intent open/running and no new direction: planner must not create a duplicate.
- Re-deliver the same graph event and result: no duplicate intent/fact/finding.

**Scenario 3 — Serial dependency chain**

- Planner proposes a multi-step sequence where B requires a fact from A and C requires a fact from B.
- A may dispatch; B and C remain pending.
- After A yields the prerequisite fact, B becomes eligible; C remains pending.
- After B yields its fact, C becomes eligible.
- Restart between A and B; dependency state and planner todos survive.

**Scenario 4 — Worker failure and lease fencing**

- Start an explore task and heartbeat it.
- Simulate worker crash / lost heartbeat; expire the claim and reassign it.
- Allow the old worker to return late; its fencing token must reject the result.
- Verify no stale Fact, Finding, anchor or edge was written.

**Scenario 5 — PentAGI refinement and recovery**

- Generate 3 subtasks; finish the first; have Refiner add one, remove one and reorder another.
- Verify exact new order/IDs and that completed evidence remains unchanged.
- Interrupt the second subtask; restart and reconcile using the saved message-chain/task state.
- Simulate invalid tool-call output; Reflector gets no more than 3 attempts and cannot claim success without a valid result.

**Scenario 6 — CAIRN contract failures**

- Reason returns complete and intents together; reject.
- Reason refers to a nonexistent fact; reject.
- Reason returns empty result with no open intents and unresolved goal; reject.
- Bootstrap conclude returns completion; reject.
- Explore returns extra/missing required fields; reject or run allowed conclude fallback according to the exact reference rules.
- Cancel the engagement during a worker call; no conclude fallback and no graph write.

**Scenario 7 — Multi-worker and multi-engagement isolation**

- Run two independent intents on separate workers; verify per-intent leases and task/subtask ordering.
- Run two engagements concurrently; verify no facts, assets, credentials, traces or memory cross their permitted scope.
- Run two dispatcher processes for one engagement; only one obtains authoritative scheduling ownership.

**Scenario 8 — Security boundary and prompt injection**

- Put hostile instructions in HTTP responses, page content, source comments and worker trace strings.
- Verify none can change the goal, target, scope, allowed tool set, task contract, budget or approval policy.
- Verify worker process lacks graph/database write credentials.
- Verify every actual tool call reaches the scope/egress/approval/budget boundary, including specialist agents and fallback tools.

### 7.6 AI-generated evidence artefacts

The implementation agent must write:

```text
docs/conformance/
  reference-pins.md
  artex-graph-conformance.md
  pentagi-delegation-conformance.md
  cairn-protocol-conformance.md
  integrated-e2e-results.md
  deviations.md
```

Include machine-readable JSON where helpful:

```json
{
  "reference_commits": {
    "artex": "94757c5d7e704ac1c095ee99e97d9ac4d9d428c5",
    "pentagi": "cffed9485aa1cca70762cd08a57ac62a80406258",
    "cairn": "8e7e0ea67552383851dfcabfba0c4e9c8d007878",
    "argus_baseline": "0e006958927c82d95d293f4e08262df79d95e921"
  },
  "requirements": {
    "A-01": {"status": "PASS", "tests": ["..."], "runtime_evidence": "..."},
    "P-01": {"status": "NOT VERIFIED", "tests": [], "runtime_evidence": null},
    "C-01": {"status": "PARTIAL", "tests": ["..."], "runtime_evidence": null}
  }
}
```

The example statuses above are placeholders, not claims about implementation results.

---

## 8. Recommended delivery order and release gates

The three workstreams should be developed in the requested conceptual order, but the control-plane contract is a prerequisite for graph writes and delegated execution.

### Stage 0 — Architecture lock and baseline

- Pin sources and Argus baseline.
- Define graph/task/intent/fact contracts.
- Define authoritative storage backend per deployment mode.
- Define one dispatcher/write owner.
- Add conformance test skeletons before implementation.

**Gate:** no duplicate planner or dual-write path exists in the design.

### Stage 1 — CAIRN control-plane skeleton

- Implement typed `bootstrap`, `reason`, `explore` contracts.
- Implement intent/reason leases, worker registry, cancellation and single-dispatcher authority.
- Keep graph operations behind repository interfaces; initially use test adapters.

**Gate:** all `C-*` contract/lease/cancellation tests pass against the test repository.

### Stage 2 — ARTEX graph-backed exploration

- Implement canonical asset graph and per-engagement exploration graph.
- Add anchors, coverage, planner frontier, persistent todos, graph outbox and graph-change wake-up.
- Wire the ARTEX planner through CAIRN reason contract.

**Gate:** all `A-*` tests pass; no goal can be marked complete without verifier-backed proof.

### Stage 3 — PentAGI hierarchical delegation

- Implement Task/Subtask/Action persistence, Generator, Primary Agent, Refiner, specialist delegation, Reflector, Reporter and Memorist adapter.
- Map each claimed intent to one task; run subtasks sequentially within the task.

**Gate:** all `P-*` tests pass; no task can finish while required subtasks are unresolved.

### Stage 4 — Integrated end-to-end run

- Enable the integrated dispatcher → graph planner → intent → task hierarchy → tool executor → result writeback loop.
- Run all eight integration scenarios.
- Compare against the legacy Argus workflow in shadow mode, then enable only on controlled labs.

**Gate:** all critical conformance requirements pass, no high-severity safety regression, persistence/restart works, and a controlled lab assessment reaches a truthful terminal state without development-only scope bypasses.

### Stage 5 — Gradual production activation

- Enable V2 for a small set of explicitly scoped engagements.
- Track no-stall rate, duplicate intent rate, subtask refinement count, claim-loss count, verified-finding ratio, coverage, LLM/tool cost, partial-run rate and recovery rate.
- Keep a one-switch rollback to the existing Argus workflow path.

**Gate:** stability and verification metrics meet thresholds defined before rollout; do not use raw finding count as the success metric.

---

## 9. Explicit non-goals and adaptations

1. **Do not replace OpenCode or the existing Argus tool execution stack.** Reuse the existing TUI, capability registry, MCP bridge, `executeHybrid`, `ReActAgent`, tool-health handling, scope checks, verifier and report generator.
2. **Do not create three independent planners.** ARTEX is the only top-level intent planner; CAIRN defines its structured reason/dispatch protocol; PentAGI decomposes one claimed intent into subtasks.
3. **Do not turn the existing vulnerability attack graph into the ARTEX exploration graph.** Keep vulnerability risk/chain scoring separate from the asset graph and exploration graph.
4. **Do not make Docker mandatory.** Reuse Argus's execution boundary and make isolation guarantees explicit. If the configured isolation backend is unavailable, fail closed for engagements that require it; do not silently fall back to a weaker mode.
5. **Do not let workers write graph state directly.** Agents return structured output; dispatcher validates and commits.
6. **Do not claim complete parity from component presence.** Each behaviour needs a passing unit/contract test and an integration/runtime trace.
7. **Do not broaden target scope from discovered assets.** A discovered subdomain, IP, redirect or URL is not automatically authorized. Asset graph discovery and target authorization are separate checks.
8. **Do not equate a fact with a vulnerability, or a vulnerability candidate with a verified finding.** Keep the existing Argus verification and evidence lifecycle.
9. **Do not copy source code or prompts without license review.** Reproducing architecture and behaviour is different from copying implementation.

---

## 10. Definition of done

The three workstreams are complete only when all statements below are true:

- Argus has a canonical shared asset graph and per-engagement exploration graph with validated anchors and event-driven planning.
- An unresolved goal cannot stall with an empty frontier; proven goals cannot be reopened by untrusted tool output.
- Dependent intents are scheduled only after prerequisite facts exist; todo/coverage/intent state survives restart.
- One intent is claimed under a dispatcher lease, and stale workers cannot commit results.
- Each intent executes through a persistent PentAGI-style Task with an ordered subtask plan of at most 15 items.
- Subtasks run sequentially inside a task; the Primary Agent can delegate to bounded specialists; the Refiner applies deterministic patches after each terminal result; Reflector is capped at three corrections.
- CAIRN bootstrap/reason/explore schemas and lifecycle semantics are enforced by code, not prompt text alone.
- The dispatcher is the sole durable graph/task/intent writer; workers have no direct write authority.
- Facts, findings, proof, evidence, assets and task results are distinct typed records with provenance and links.
- Scope, egress, budgets, approvals, isolation, cancellation and audit logging apply to every worker and specialist action.
- All `A-*`, `P-*`, `C-*` and integrated scenarios have evidence-backed `PASS` status, or every deviation is explicitly documented and approved.
- A controlled authorized end-to-end run reaches `COMPLETED` only when the goal is proven; otherwise it ends honestly as `PARTIAL`, `INTERRUPTED` or `FAILED` with actionable reasons.

**Final instruction to the implementation AI:** optimise for behavioural fidelity and verifiable state transitions, not for the number of new files, agents or tools. Do not claim these three architectures have been implemented until the conformance ledger proves their complete runtime paths.
