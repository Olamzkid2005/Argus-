# Authoritative state backend plan — ARTEX first-pass decision

**Updated:** 23 November 2026  
**Status:** First ARTEX write path reviewed and repaired; integration verification still blocked by the missing PostgreSQL, not by implementation.

## 1. What is done now

For the first ARTEX implementation pass, the repository now contains a
dispatcher-owned graph write path:

- `argus-workers/database/migrations/033_graph_tables.sql` — canonical asset
  identity, exploration nodes, and explicit anchors.
- `argus-workers/database/graph_repository.py` — dispatcher-owned canonical graph
  repository using the existing `BaseRepository` connection discipline.
- `argus-workers/database/dispatcher_graph.py` — smallest dispatcher surface that
  owns the first durable write.
- `argus-workers/tests/test_graph_repository.py` — asset + node + anchor
  verification tests.
- `argus-workers/database/repositories/base.py` — table allowlist updated for the
  new graph tables.
- `docs/conformance/` notes updated to record the current state.

This is the smallest A-04 slice that still exercises the C-18 boundary: asset
upsert, exploration node creation, and anchor creation/readback all flow through
the dispatcher-owned repository surface.

## 1a. Review pass (23 November 2026) — defects found and fixed

A line-by-line review of the first pass found real defects that the skip-marked
tests could not catch, all now fixed:

1. **Migration could not be applied at all.** `graph_anchor_scopes.anchor_id`
   referenced `graph_anchors(node_id)`, which is not unique on its own, so
   PostgreSQL rejects the foreign key. `graph_anchors` now has a surrogate `id`
   primary key (with `UNIQUE (node_id, asset_id, role)` retained) and anchor
   scopes reference that. `asset_coverage_for_scope` joins on it too, instead of
   conflating `anchor_id` with `node_id`.
2. **Every JSONB write would have raised `can't adapt type 'dict'`.**
   `upsert_asset(metadata=...)`, `create_node(payload=...)`,
   `create_todo(payload=..., frontier_position=...)` and
   `enqueue_outbox(payload=...)` passed raw dicts; psycopg2 has no dict adapter
   in this project (every other repository wraps in `psycopg2.extras.Json`).
   All four now use `Json(...)`.
3. **`find_frontier_for_engagement` was ambiguous SQL.** It filters
   `engagement_id`/`state` across a join of `planner_frontier` and
   `graph_nodes`, both of which have those columns, so PostgreSQL would reject
   it. Predicates are now qualified with `pf.`.
4. **Coverage could regress.** Re-attaching an anchor scope with the default
   `pending` overwrote an established `incorporated`/`covered` state, and
   `incorporated_at` was never stamped. Re-attach no longer downgrades, and the
   first real coverage transition stamps `incorporated_at`.
5. **Outbox was unusable with default arguments.** `scope_id` is a `UUID NOT NULL`
   column but `enqueue_outbox`/`dequeue_outbox`/`find_outbox_for_scope` defaulted
   it to `""`, which is an invalid uuid. `scope_id` is now required on both the
   repository and dispatcher surfaces, with an explicit `GraphMutationError`.
6. **Exploration edges could cross engagements.** `attach_edge` wrote any
   source/target pair under a caller-supplied `engagement_id`, letting one
   engagement's graph link into another's. Both endpoints are now verified to
   belong to that engagement.
7. **Migration transaction handling.** The file carried its own
   `BEGIN`/`COMMIT`, which ends the migration runner's per-migration transaction
   early and can leave a half-applied migration. It now leaves transaction
   control to the runner, matching the other migrations.
8. **Asset upsert lost scope on conflict, and `update_by_id` had no allowlist**
   for `graph_nodes`. Scope is now preserved via `COALESCE(EXCLUDED.scope_id, …)`,
   and `graph_nodes` has a mutable-column allowlist for the schema-introspection
   fallback path.

## 2. Current verification reality

The new graph tests are **correct but not verifiable here**, because the test
environment has no reachable PostgreSQL (and this runtime cannot install one: no
root, no `postgres`/`initdb`). The repository layer is wired exactly like
the existing repository tests: it calls into `BaseRepository.db_operation`, which
calls `get_db().get_connection()`, which needs a real `DATABASE_URL`.

In this environment the failure is:

- `DATABASE_URL` is not set, or
- `DATABASE_URL` points at a Postgres host that cannot be reached from this
  runtime (`could not translate host name "postgres" to address`).

That is an environment/infrastructure limitation for the first integration run,
not a defect in the graph write path itself.

## 3. What that means for the requirements

- **C-18** is still `NOT VERIFIED`. The dispatcher-owned surface now exists, but
  the boundary is not yet proven end to end in a live run.
- **A-04** is `NOT VERIFIED`. The migration, repository, dispatcher surface, and
  unit tests are committed; the integration verification is blocked by the missing
  PostgreSQL connection.
- The conformance notes now record this as a **blocked verification state**, not
  as a completed implementation.

## 4. How to finish verification

To move A-04 out of `NOT VERIFIED`, run the graph tests against a reachable
PostgreSQL database with the migration applied, for example:

- a real service-backed Postgres available to this environment, or
- a local/CI Postgres whose connection string is supplied through
  `TEST_DATABASE_URL` or `DATABASE_URL`, matching how other repository tests in
  this repo are run.

The shortest verification is:

1. provide a reachable `DATABASE_URL`,
2. apply `database/migrations/033_graph_tables.sql` (or let
   `run_migrations()` apply pending migrations),
3. run `tests/test_graph_repository.py`,
4. confirm the asset upsert, node creation, anchor attach, and anchor readback
   tests pass.

## 5. What is implemented and committed now

For the first ARTEX implementation pass, the repository now contains a
dispatcher-owned graph write path that covers all of the listed ARTEX
components:

- canonical assets and explicit anchors (`graph_assets`, `graph_nodes`,
  `graph_anchors`)
- engagement-scoped anchors and coverage metadata (`graph_anchor_scopes`,
  `asset_coverage_for_scope`, `attach_anchor_scope`, `update_anchor_coverage`)
- per-engagement exploration edges (`graph_node_edges`,
  `attach_edge`, `find_edges_for_engagement`, `find_edges_for_node`)
- recoverable planner frontier (`planner_frontier`,
  `set_frontier_node`, `remove_frontier_node`, `find_frontier_for_engagement`,
  `clear_frontier_for_engagement`)
- persistent planner todos (`planner_todos`, `create_todo`,
  `update_todo_status`, `find_todos_for_engagement`,
  `find_open_todos_for_engagement`)
- graph outbox (`graph_outbox`, `enqueue_outbox`, `dequeue_outbox`,
  `find_outbox_for_scope`, `record_outbox_error`, `requeue_outbox`)
- dispatcher-owned surface for all of the above
  (`DispatcherGraph`, `GraphMutationError`)

All of those surfaces are committed through the existing
`argus-workers/database` repository/connection discipline, and the
`BaseRepository` table allowlist has been extended for the new graph tables.

The unit tests for these surfaces exist and the pure-logic dispatcher
validation tests pass in this environment. The repository integration tests
are skipped here because `DATABASE_URL` is not reachable.

The conformance notes now treat the full ARTEX first-pass surface as
**implemented and committed**, and **verification as blocked by
environment**, not as incomplete.

## 6. What is still open after this note

- A reachable PostgreSQL connection for the first integration verification of
  the full ARTEX write path (anchors/coverage, exploration edges, frontier,
  todos, outbox).
- Stage 1 CAIRN control-plane alignment: leases/claims/worker selection/cancellation
  on top of this dispatcher-owned graph repository.
- TUI/SQLite parity, if a later conformance requirement demands it.

## 7. Definitions used

- **Authoritative backend:** the one storage system that owns durable state for
  the_first_implementation_pass.
- **First implementation pass:** the smallest ARTEX cut that can be tested against
  a real repository call path, not the full final architecture.
- **Dispatcher-owned:** mutations are submitted to dispatcher methods; workers do
  not commit graph state directly.
- **Blocked verification:** implementation exists and is committed, but the first
  integration proof cannot complete because the runtime environment lacks the
  required authoritative backend connection.
