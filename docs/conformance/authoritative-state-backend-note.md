# Authoritative state backend plan — ARTEX first-pass decision

**Updated:** 22 November 2026  
**Status:** Stage 0 decisions resolved for the first ARTEX implementation pass.  
**Not done:** the ARTEX layer itself; this file records only the decisions that
must exist before code is written.

## 1. What this note resolves now

Before the ARTEX workstream can start, three Stage 0 questions had to be
answered precisely enough to test:

1. Which deployment mode owns the first durable graph write.
2. Which existing backend is authoritative for that mode.
3. How the ARTEX graph layer relates to the existing attack graph, so the two
   are not confused or merged.

This note records those answers for the **first ARTEX implementation pass only**.
It does not claim full parity across every deployment mode, and it does not
create a third state store.

## 2. Chosen deployment mode for the first ARTEX pass

**First durable write owner: Python / PostgreSQL path.**

The conformant first cut is the Python service-backed path because:

- The repository already has a PostgreSQL-backed repository layer
  (`argus-workers/database/`) and a connection/pool setup
  (`argus-workers/database/connection.py`).
- The ARTEX layer needs durable graph state (assets, exploration nodes/edges,
  anchors, planner todos, outbox) plus compare-and-set claim/lease semantics.
  That is much easier to prove first against a real PostgreSQL-backed repository
  than against the TUI’s local per-engagement SQLite path.
- The plan forbids dual-writing SQLite and PostgreSQL or inventing a third store.
  So the first pass picks one authoritative backend and makes the choice explicit.

This choice is for the **first implementation pass**, not the final deliverable.
SQLite parity for the TUI/local path is out of scope for this first pass unless
a later conformance requirement explicitly demands it.

## 3. Authoritative backend for the first pass

For the first ARTEX pass, the authoritative state backend is PostgreSQL, accessed
through the repository pattern already used in `argus-workers/database/`.

That means:

- A new `EngagementGraphRepository` is the dispatcher-owned persistence contract
  for the first cut.
- It uses the same connection discipline the existing repositories use: accept an
  external connection where transactions matter, otherwise use the repository’s
  normal connection handling.
- The dispatcher, not workers or agents, is the only component that commits
  durable graph/task/intent transitions through this repository.
- No worker, MCP tool wrapper, or agent path is allowed to import and write to
  the graph repository directly; that is the C-18 boundary.

## 4. What ARTEX owns, in this first pass

For the first implementation pass, the ARTEX layer is the canonical graph layer.
It owns:

- a shared **asset graph** (per engagement/scope-boundary), with canonical asset
  identity, edges, and observations
- a per-engagement **exploration graph**, with goal, intent, fact, finding, and
  hint nodes and typed edges
- **anchors** linking exploration nodes to assets
- **coverage** derived from anchors and approved scope
- **planner frontier** and a persistent **planner todo** list
- a **graph outbox** for committed graph-change events

The existing attack graph (`attack_graph.py` / `attack_graph_db.py`) is **not**
the ARTEX exploration graph and is **not** repurposed as one. Vulnerability
chain/risk scoring stays separate.

## 5. Symbolic table for the first-pass implementation

| Concept | First-pass owner | Notes |
|---|---|---|
| Shared asset graph | ARTEX | One canonical asset per identity per scope boundary |
| Exploration graph | ARTEX | Per-engagement; goal/intent/fact/finding/hint nodes |
| Anchors | ARTEX | Explicit, validated many-to-many node ↔ asset links |
| Coverage | ARTEX | Derived from anchors + approved scope |
| Planner frontier + todos | ARTEX | Persistent, prerequisite-aware, survives restart |
| Graph outbox | ARTEX | Committed change events, same transaction as the mutation |
| Dispatcher/writer authority | CAIRN | Only dispatcher commits durable graph state |
| Task/subtask/action hierarchy | PentAGI | One task per claimed intent; sequential subtasks |
| Attack graph / vulnerability chain scoring | Existing Argus | Separate from ARTEX exploration graph |

## 6. What C-18 now means for ARTEX

C-18 is no longer just an abstract control rule. For the ARTEX first pass it
means:

- there is one dispatcher-owned graph repository interface,
- workers/agents return structured output and never import/use the graph
  repository to commit state directly,
- the first conformance tests prove that boundary with a real repository call
  path, not with mocks alone.

## 7. What is still open after this note

- The actual `EngagementGraphRepository` interface and first PostgreSQL-backed
  implementation.
- The smallest testable dispatcher surface that can own the first durable write.
- Alignment with the Stage 1 CAIRN control-plane skeleton (leases, claims,
  worker selection, cancellation), since ARTEX writes are supposed to flow
  through CAIRN ownership.
- TUI/SQLite parity, if a later requirement demands it.

## 8. Definitions used

- **Authoritative backend:** the one storage system that owns durable state for
  the_first_implementation_pass.
- **First implementation pass:** the smallest ARTEX cut that can be tested against
  a real repository call path, not the full final architecture.
- **Dispatcher-owned:** mutations are submitted to dispatcher methods; workers do
  not commit graph state directly.
