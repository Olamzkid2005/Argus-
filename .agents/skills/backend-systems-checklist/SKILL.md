---
name: backend-systems-checklist
description: Use when writing, reviewing, debugging, or designing backend code and systems — especially anything touching databases, transactions, locking, queries, migrations, caches, queues, workers, retries, webhooks, or distributed calls. Enforces a concrete audit of race conditions, deadlocks, ACID/isolation, pooling, N+1, indexes, cache invalidation, idempotency, backoff, DLQs, backpressure, shutdown, tracing, and memory leaks.
---

# Backend Systems Checklist

Apply the relevant sections **before** designing and **after** changing backend code.
For a review, cite the concrete line or query that triggers a finding; never report a
category as "fine" without looking at the code that would fail.

## 1. Concurrency and correctness

- **Race conditions** — identify shared mutable state (module singletons, stores, files,
  DB rows, env vars) and every writer. Ask: what happens if two callers interleave here?
  Prefer per-owner state, immutable snapshots, and a single writer.
- **Deadlocks** — check lock acquisition order across code paths; require a total order or
  a timeout + retry. Watch for lock-held-while-awaiting I/O.
- **Optimistic locking** — version/`updated_at` predicate in the `UPDATE ... WHERE`; retry on
  zero rows affected. Never read-modify-write without a version check.
- **Pessimistic locking** — `SELECT ... FOR UPDATE` (or an advisory lock) with a bounded wait;
  ensure every path releases it, including errors.
- **Idempotency** — every retryable mutation needs a natural key or idempotency key. Ask what
  a duplicate delivery/click/retry does.
- **Distributed transactions** — avoid 2PC. Use a transactional outbox or a saga with
  compensating actions, and make each step idempotent.

## 2. Database core

- **ACID / transactions** — the unit of work must match the invariant. No partial writes;
  no transaction left open across network calls or UI awaits.
- **Isolation levels** — know the engine default (SQLite serializable-ish, Postgres read
  committed). Name the anomaly you are preventing (dirty read, lost update, write skew,
  phantom) and check the level actually prevents it.
- **Foreign keys / unique constraints** — enforce invariants in the schema, not only in code.
  Check `ON DELETE` behavior and that SQLite `PRAGMA foreign_keys=ON` is set.
- **Connection pooling** — bound pool size, set acquire/statement timeouts, and confirm every
  connection is released on the error path. Pool exhaustion is a common outage.
- **N+1 queries** — inspect loops that query per item; batch with `IN (...)`, joins, or a
  dataloader.
- **Indexes** — index the columns used by `WHERE`, `JOIN`, `ORDER BY`, and uniqueness rules.
  Composite index order matters; an unused index still costs writes.
- **Query optimization / EXPLAIN ANALYZE** — measure before and after. Look for full scans,
  temp B-trees, bad row estimates, and repeated identical queries.
- **Migrations** — forward-only, deterministic, reviewed, and tested on a copy. Never edit an
  applied migration. **Zero-downtime**: expand → backfill → switch reads → contract; no
  blocking `ALTER` on large tables, no long locks, no destructive step in the same release.

## 3. Scale, replication, and topology

- **Read replicas** — route only tolerant reads; never read-your-own-write from a replica.
- **Replication lag** — bound it, monitor it, and fail over to primary when a read must be
  current.
- **Sharding / partitioning** — choose a key with even distribution and stable routing;
  document cross-shard queries and rebalancing.
- **Load balancing / reverse proxies** — preserve client IP and proto headers safely, set
  sane timeouts, and verify health-check paths do not touch dependencies they should not.
- **Horizontal vs vertical scaling** — prefer stateless processes. Any in-memory state
  (locks, counters, sessions, caches) breaks horizontal scaling unless externalized.

## 4. Caching

- **Cache invalidation** — every key needs an owner, a TTL, and a write path that invalidates
  it. Prefer write-through/versioned keys over scattered deletes.
- **Redis eviction** — set `maxmemory` + policy; never store durable state only in Redis.
  Treat every key as evictable unless persistence is proven.
- **Cache stampedes** — single-flight / `Effect.cached` / mutex on miss, plus TTL jitter.
- **Distributed caching** — serialize deliberately, version the value shape, and never cache
  secrets or per-user authorization decisions without a key that includes the principal.

## 5. Reliability and messaging

- **Retry mechanisms** — retry only transient failures, cap attempts, and never retry
  non-idempotent work blindly.
- **Exponential backoff + jitter** — required together; full jitter avoids synchronized
  retry storms.
- **Circuit breakers** — open on consecutive failures, half-open probe, and fail fast with a
  clear error instead of queueing forever.
- **Rate limiting** — per principal and per target, with a documented algorithm (token
  bucket) and a 429/retry-after contract.
- **Message queues / background workers** — bound concurrency, visibility/ack timeouts, and
  poison-message handling. Workers must be restart-safe.
- **Dead letter queues** — every queue needs one, with an alarm and a replay procedure.
- **Job scheduling** — make jobs idempotent, skip overlapping runs, and record last/next run.
- **Event-driven architecture** — define delivery semantics (at-least-once vs exactly-once),
  ordering guarantees, and schema evolution.
- **Webhooks** — **verify** signatures against the raw body with a constant-time compare and
  a replay window; **retry** deliveries with backoff and dedupe by event ID.
- **Eventual consistency** — make the convergence window visible; never show a success state
  that the system has not durably reached.
- **Outbox / CQRS / event sourcing** — use only when the invariant requires it. CQRS needs a
  read-model rebuild story; event sourcing needs versioning and snapshots.
- **Backpressure** — bounded queues and explicit rejection/`429`/`503`. Unbounded buffering is
  a memory leak with extra steps.

## 6. Operability

- **Graceful shutdown** — stop accepting work, drain in-flight jobs with a deadline, flush
  buffers, release locks, then exit non-zero only on real failure.
- **Health checks** — separate liveness (process alive) from readiness (dependencies usable);
  readiness must not flap on a slow dependency.
- **Distributed tracing** — propagate a correlation/run/engagement ID across process
  boundaries (TS bridge → Python worker → tools) and log it on every hop.
- **Memory leaks** — remove listeners, clear timers/intervals, abort controllers, close
  streams/subprocesses, and cap caches. For long-lived TUI/worker processes, assert cleanup
  in tests (`listenerCount`, handles).
- **Connection pools (again)** — leaks here are the most common cause of "works until it
  doesn't". Verify close/release in `finally`.

## Project-specific hot spots

- **SQLite engagement store** — WAL mode, `busy_timeout`, single-writer discipline, and no
  transaction spanning an `await` that does network/tool work.
- **Redis autonomous lock** — TTL + owner token (release via compare-and-delete Lua), renewal
  for long runs, and clock-skew tolerance.
- **Python MCP worker / Celery** — kill owned process groups, cap stdout buffering, reconnect
  the bridge on failure, use `acks_late` + idempotent tasks, and never leave orphan scanners.
- **Scan/assessment pipeline** — serialized progress queues, no double engagement creation,
  and terminal state that a late event cannot flip back to success.

## Review questions to answer explicitly

1. What are the concurrent writers, and what serializes them?
2. Which transaction/invariant boundary can be half-applied?
3. What happens on duplicate delivery, retry, or replay?
4. What happens when the dependency is slow, down, or returns garbage?
5. What is bounded here (queue, pool, buffer, retry, cache)?
6. What cleans this up on error, timeout, and shutdown?
7. How would we know it broke in production (log, metric, trace, health check)?

## Anti-patterns to flag

- Unbounded `Promise.all`, queues, or in-memory maps.
- `await` inside an open DB transaction.
- Retry loops without jitter, caps, or idempotency.
- Cache writes without invalidation or TTL.
- Health checks that only prove the process is running.
- `catch {}` that swallows a failed transaction or lock release.
- Success reported before the write is durable.
