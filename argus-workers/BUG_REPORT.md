# Argus Scanning Pipeline — Deep Logic Audit

## BUG 1 [DATA-LOSS] — Recon context never saved before scan dispatch
- **File:** `recon.py` lines 58–83
- **Bug Type:** data-loss
- **Description:** `run_recon()` calls `ctx.orchestrator.run_recon(ctx.job)` (line 59) which generates a ReconContext, but `save_recon_context()` is **never called** before the scan task is dispatched (lines 72–78). The scan at `scan.py:37` calls `load_recon_context()` which will always return `None` because nothing was saved.
  
  Confirmation: `expand_recon()` (recon.py:127–138) explicitly checks `result.get("recon_context")` and saves it — proving the orchestrator does NOT persist it internally and relies on the task to do so.

- **Reproduction Path:** Run any normal engagement. In scan phase, `recon_context` is always `None`.
- **Fix:** In `run_recon()`, after `result = ctx.orchestrator.run_recon(ctx.job)`, add:
  ```python
  if result.get("recon_context"):
      save_recon_context(engagement_id, result["recon_context"])
  ```
  (before dispatching scan on line 72)

---

## BUG 2 [LOGIC] — `expand_recon` dispatches context too late (post-scan)
- **File:** `recon.py` lines 127–138 vs `scan.py` line 37
- **Bug Type:** logic
- **Description:** `expand_recon()` saves recon context to Redis, but it is called from `analyze.py` (line 74) — i.e., **after** the scan phase has already started. The scan loads recon context at startup (`scan.py:37`), so any context saved by `expand_recon` arrives too late to influence the scan. The recon → scan context handoff is fundamentally broken.
- **Reproduction Path:** Any engagement where `expand_recon` produces recon context → scan never sees it.
- **Fix:** Either (a) save recon context in `run_recon()` before dispatching scan (see Bug 1), or (b) pass recon context via Celery task args instead of Redis when dispatched in-band.

---

## BUG 3 [DEAD-CODE] — Unreachable `else` branch in analyze action routing
- **File:** `analyze.py` lines 91–99
- **Bug Type:** dead-code
- **Description:** The `else` branch at line 91 is inside `if _dispatched == 0:` which is inside `if actions:` (line 37). Since `actions` is non-empty/truthy by the time we reach line 87's `if actions:`, the `else` at line 91 can **never** execute. The code that was supposed to handle "all actions had invalid/empty targets" by transitioning to "reporting" is dead. Instead, when all actions have invalid targets, the code at line 89–90 transitions to `"failed"` (too aggressive).
- **Reproduction Path:** Return analysis results with actions that have empty targets → engagement goes to "failed" instead of "reporting".
- **Fix:** Restructure the flow so the case `actions non-empty but all targets invalid` transitions to `"reporting"` instead of `"failed"`, and the dead `else` block is either removed or its logic is moved to the correct scope.

---

## BUG 4 [RACE] — State transition after dispatch in `run_recon`
- **File:** `recon.py` lines 58–83
- **Bug Type:** race
- **Description:** `run_recon()` dispatches `asset_discovery` (line 62) and `scan` (line 73) **before** transitioning the engagement state to `"scanning"`. The state remains `"recon"` while downstream tasks are enqueued. If `scan.py` runs before `run_recon()` finishes its `return`, another worker could observe the engagement in `"recon"` state when it expects `"scanning"`.
  
  Contrast with `scan.py` lines 73–80 which correctly transitions to `"analyzing"` **before** dispatching the analyze task.

- **Reproduction Path:** Tight timing between recon finishing and scan starting → scan's `_get_engagement_state()` may return "recon" instead of "scanning".
- **Fix:** Move the state transition to `"scanning"` BEFORE dispatching asset_discovery and scan tasks.

---

## BUG 5 [SILENT-FAILURE] — Unused `os.getenv("DATABASE_URL")` result
- **File:** `report.py` line 154
- **Bug Type:** dead-code
- **Description:** `os.getenv("DATABASE_URL")` is called but its return value is discarded (no assignment). This is a no-op line.
- **Reproduction Path:** Static analysis.
- **Fix:** Remove the line.

---

## BUG 6 [LOGIC] — `LoopBudgetManager` instantiated but never used
- **File:** `llm_review.py` lines 126–131
- **Bug Type:** dead-code
- **Description:** `LoopBudgetManager` is instantiated with `LoopBudgetManager(engagement_id, budget or {})` but the result is **not assigned** to a variable. The object is immediately garbage collected. Budget enforcement is completely absent.
- **Reproduction Path:** Any LLM review run — budget is never checked or enforced.
- **Fix:** Assign to a variable and use it to enforce budget limits in the analysis loop (line 155), or remove the dead instantiation.

---

## BUG 7 [LOGIC] — `budget_exhausted` is always `False`
- **File:** `llm_review.py` lines 153, 244
- **Bug Type:** dead-code
- **Description:** `budget_exhausted = False` is set on line 153 but **never updated** anywhere in the function. The log message on line 244 always prints `"all processed"` regardless of actual budget state. The budget tracking variable is dead code.
- **Reproduction Path:** Run LLM review with exhausted budget → outputs "all processed".
- **Fix:** Either implement actual budget checking logic or remove the variable and simplify the log message.

---

## BUG 8 [CONNECTION-LEAK] — Asset discovery does not close connection on error
- **File:** `asset_discovery.py` lines 113–114, 123–128
- **Bug Type:** data-loss / resource-leak
- **Description:** In the `except` handler (lines 123–128), the function returns early without calling `cursor.close()` or `conn.close()`. The connection is leaked. Additionally, `conn.commit()` is never called on the error path, leaving the transaction open (holding locks on any affected rows).
- **Reproduction Path:** Raise an exception during the INSERT or UPDATE in `run_asset_discovery` → PostgreSQL connection leaks.
- **Fix:** Restructure with `try: ... except: ... finally: cursor.close(); conn.close()` pattern, or use a context manager. Also call `conn.rollback()` in the except block.

---

## BUG 9 [LOGIC] — Implicit `None` return from `fetch_engagement_scan_options` when row not found
- **File:** `utils.py` lines 149–170
- **Bug Type:** logic / crash-risk
- **Description:** If the `SELECT` query returns no row (engagement doesn't exist), the function falls through without an explicit `return` and returns `None` implicitly. Callers like `expand_recon()` (recon.py:144, 160–163) and `deep_scan()` / `auth_focused_scan()` (scan.py:100, 110–113) do `opts["agent_mode"]` etc. which raises `TypeError: 'NoneType' object is not subscriptable`.
- **Reproduction Path:** An engagement whose row is deleted between enqueue and execution.
- **Fix:** After the `if row:` block, add:
  ```python
  if not row:
      logger.error("Engagement %s not found for scan options", engagement_id)
      return defaults
  ```

---

## BUG 10 [SECURITY] — `_replay_request` sends live HTTP GET to target with user-controlled payload
- **File:** `llm_review.py` lines 255–291
- **Bug Type:** security
- **Description:** `_replay_request()` sends an actual HTTP GET request to the target endpoint with the finding's payload as a query parameter (`?q=<payload>`). If the target is a production system, this could trigger side effects (log pollution, WAF alerts, rate-limit impacts, or in rare cases, state-changing GET requests). The User-Agent string reveals `Argus-LLM-Review/1.0`.
- **Reproduction Path:** LLM review processes a finding from a production engagement → sends live HTTP traffic.
- **Fix:** At minimum, require explicit opt-in for live replay. Better: use a dry-run mode that only analyzes stored responses. Also avoid leaking payload in query params — use stored responses when available.

---

## BUG 11 [SILENT-FAILURE] — `except Exception: pass` on UI notification failure
- **File:** `scan.py` lines 47–48
- **Bug Type:** silent-failure
- **Description:** When `emit_thinking()` fails (e.g., Redis/WebSocket down), the exception is swallowed silently with `pass`. No log, no warning. Admin won't know the UI is not receiving real-time updates.
- **Reproduction Path:** WebSocket server is down; engagement runs normally but UI shows no thinking updates.
- **Fix:** Replace `pass` with `logger.warning(...)`.

---

## BUG 12 [RACE] — `analyze.py` state check + transition not atomic
- **File:** `analyze.py` lines 22–25, 33, 90
- **Bug Type:** race
- **Description:** `run_analysis()` first checks `_get_engagement_state() != "analyzing"` and returns early if so (lines 22–25). Then later, `task_context` at line 33 initializes the state machine with `current_state="analyzing"`. If another worker transitions the state between the check and the state machine init, the `state_machine.transition()` in `_persist_state_and_budget` will detect the race via `SELECT ... FOR UPDATE` and either re-check the transition or raise. The early-return check is a TOCTOU optimization — not incorrect, but misleading. The real guard is the DB lock.
- **Reproduction Path:** Two analyze tasks dispatched for the same engagement; state is double-checked.
- **Fix:** Remove the TOCTOU pre-check at lines 22–25 and let the state machine handle it. Or keep it for early-exit optimization but add a clarifying comment.

---

## BUG 13 [LOGIC] — `_dispatched == 0` with actions but all empty/invalid → transitions to `"failed"` (too aggressive)
- **File:** `analyze.py` lines 85–90
- **Bug Type:** logic
- **Description:** When actions are present but none produce valid targets (e.g., all `deep_scan` actions with empty `targets` lists), `_dispatched` stays 0. The code transitions to `"failed"` with "All action dispatches failed". This should arguably transition to `"reporting"` since the analysis itself completed — the actions just had no actionable data. The dead `else` branch (Bug 3) was supposed to handle this differently.
- **Reproduction Path:** Analysis returns actions with empty/None targets → engagement incorrectly fails.
- **Fix:** If actions exist but all have invalid targets, transition to `"reporting"` instead of `"failed"`, since the analysis phase successfully completed.

---

## BUG 14 [DATA-INTEGRITY] — `generate_compliance_report` can insert NULL `org_id`
- **File:** `report.py` lines 401–417
- **Bug Type:** data-integrity
- **Description:** If the engagement's `org_id` lookup returns None (line 405: `org_id = org_row["org_id"] if org_row else None`), the INSERT at line 417 passes `None` for `org_id`. The `compliance_reports` table's `org_id` column may have a `NOT NULL` constraint (foreign key to organizations), causing an INSERT failure.
- **Reproduction Path:** Engagement has no org_id or the org was deleted → compliance report generation fails with constraint violation.
- **Fix:** Validate `org_id` before inserting. If `None`, raise a clear error before attempting the INSERT.

---

## BUG 15 [RACE] — FOR UPDATE lock held across long-running LLM calls
- **File:** `database/repositories/finding_repository.py` lines 543–565 (`find_unreviewed_low_confidence`)
- **Bug Type:** race / performance
- **Description:** The `find_unreviewed_low_confidence()` method uses `SELECT ... FOR UPDATE SKIP LOCKED` to select findings, but the cursor and connection are closed/returned to pool **without** an explicit `COMMIT` or `ROLLBACK`. The connection is returned to the pool still holding the `FOR UPDATE` lock. The lock is only released when that connection is checked out of the pool for its next query which does a commit/rollback. This can cause findings to be locked for an extended period, and `SKIP LOCKED` causes other workers to skip those rows (which is the intent), but the uncertainty of when the lock is released is a problem.
- **Reproduction Path:** Multiple LLM review workers processing the same engagement — findings may be locked longer than expected.
- **Fix:** Add `conn.commit()` (or `conn.rollback()`) before `_release_connection()` to release the FOR UPDATE locks immediately.

---

## BUG 16 [SILENT-FAILURE] — `except Exception: pass` in `LlmCostTracker._get_current_cost`
- **File:** `utils.py` line 84
- **Bug Type:** silent-failure
- **Description:** If `self._redis.get()` fails (e.g., connection error), the exception is silently swallowed with `pass`. The method falls through to `return self._local_spend`, which is a stale value. The caller doesn't know Redis tracking is degraded.
- **Reproduction Path:** Redis becomes temporarily unavailable during an LLM cost check.
- **Fix:** Add `logger.debug()` or `logger.warning()` before the `pass`.

---

## BUG 17 [LOGIC] — `diff_result[engine.CAT_FIXED]` direct key access can raise `KeyError`
- **File:** `diff.py` line 84
- **Bug Type:** logic
- **Description:** `diff_result.get(engine.CAT_FIXED, [])` on line 78 correctly uses `.get()` with a default, but line 84 accesses `diff_result[engine.CAT_FIXED]` directly (without `.get()`). If the `engine.diff()` result does not contain the `CAT_FIXED` key, this raises `KeyError`.
- **Reproduction Path:** ScanDiffEngine returns a diff result without the CAT_FIXED key (e.g., for first-scan or empty diff).
- **Fix:** Change to `diff_result.get(engine.CAT_FIXED)` which safely returns None, or `diff_result.get(engine.CAT_FIXED, [])` to match line 78.

---

## BUG 18 [RACE] — Comments contradict actual ordering in expand_recon
- **File:** `recon.py` line 140
- **Bug Type:** documentation / logic
- **Description:** Line 140 says `"# Dispatch downstream task BEFORE transitioning state"` but the code at lines 146–171 does the **opposite**: transition first, then dispatch. Line 145 correctly states `"# Transition first so if it fails, no orphaned downstream task"`. The comment on line 140 is stale and misleading.
- **Fix:** Update/remove the stale comment on line 140.

---

## BUG 19 [LOGIC] — `scan.py` returns success result even after transition to `"failed"`
- **File:** `scan.py` lines 77–80, 88–90
- **Bug Type:** logic
- **Description:** When the transition to `"analyzing"` fails (line 77–80), the code transitions to `"failed"` but then **returns the scan result as if it succeeded** (`return result`). Similarly at lines 88–90, if the analyze dispatch fails, it transitions to `"failed"` but falls through to `return result` (line 92) — the failed state is not reflected in the return value. Callers checking the return value will see a success result.
- **Reproduction Path:** State machine fails during transition to analyzing → `run_scan` returns `{...}` (success-looking) despite failed state.
- **Fix:** Return a failure-indicating result after transitioning to failed:
  ```python
  ctx.state.transition("failed", ...)
  return {**result, "status": "failed", "reason": "state_transition_failed"}
  ```

---

## BUG 20 [LOGIC] — No `ROLLBACK` on asset_discovery exception path leaves transaction open
- **File:** `asset_discovery.py` lines 123–128
- **Bug Type:** data-loss
- **Description:** The `except` handler returns without calling `conn.rollback()`. The open transaction holds locks on any rows modified by the partial execution (e.g., if the first INSERT succeeded but the UPDATE failed). The connection is also leaked (see Bug 8). The next check-out of this connection from the pool may continue the stale transaction.
- **Reproduction Path:** Partial failure during asset discovery → stale transaction leaks into the connection pool.
- **Fix:** Add `conn.rollback()` in the `except` block before returning (in addition to the connection cleanup from Bug 8).

---

## BUG 21 [DEAD-CODE] — `generate_scheduled_reports` has unreachable `os.getenv` result
- **File:** `report.py` line 154
- **Bug Type:** dead-code
- **Description:** Already noted in Bug 5. Included here for completeness since it's in the report context.

---

## BUG 22 [RACE] — `generate_report` idempotency check has TOCTOU window
- **File:** `report.py` lines 40–47
- **Bug Type:** race
- **Description:** The idempotency check queries `_get_engagement_state()` and returns early if `"complete"`. Between this check and `ctx.state.safe_transition("complete")` at line 58, another worker could set the state to `"complete"`. This is partially mitigated by `safe_transition` which skips if there's no valid outgoing transition (terminal states `complete`/`failed` have none). However, the report could still be generated twice in rare timing conditions.
- **Fix:** Acceptable risk since `safe_transition` provides the guard. Add a comment documenting the mitigated TOCTOU.

---

## BUG 23 [LOGIC] — `save_recon_context` and `load_recon_context` create new Redis connections each call
- **File:** `utils.py` lines 88–103, 106–134
- **Bug Type:** performance
- **Description:** Every call to `save_recon_context` and `load_recon_context` creates a new Redis connection via `redis.from_url()` and immediately closes it. No connection pooling. For high-throughput engagements, this is wasteful (TCP handshake + teardown per call).
- **Reproduction Path:** Multiple engagements running concurrently → many Redis connections created.
- **Fix:** Use a Redis connection pool or a shared client instance.

---

## BUG 24 [LOGIC] — `_replay_request` URL encoding is fragile
- **File:** `llm_review.py` line 280
- **Bug Type:** logic
- **Description:** `urlencode({'q': payload}).split('=')[1]` extracts the URL-encoded payload. While it works for simple payloads, it assumes the first `=` in the output is the key-value separator. For a payload like `"a=b"`, `urlencode({'q': 'a=b'})` produces `q=a%3Db`, and `.split('=', 1)[1]` gives `a%3Db` which is correct. But the `.split('=')` without `maxsplit=1` splits on ALL `=` signs. For almost all cases this works since only the `q` key is present, but it's fragile.
- **Fix:** Use `urlparse.parse_qs()` or `urllib.parse.urlencode()` directly:
  ```python
  from urllib.parse import urlencode
  test_url = f"{endpoint}?{urlencode({'q': payload})}"
  ```

---

## BUG 25 [SECURITY] — Hardcoded `redis://localhost:6379` default
- **File:** Multiple files: `scan.py:35`, `base.py:91`, `utils.py:40`, `utils.py:98`, `utils.py:121`
- **Bug Type:** security
- **Description:** Multiple places hardcode `redis://localhost:6379` as the fallback Redis URL. In production deployments where `REDIS_URL` is not set, this defaults to localhost, which may not be the intended Redis instance. This could lead to cross-tenant data leakage or data loss if multiple engagements accidentally share a localhost Redis.
- **Reproduction Path:** Deploy without `REDIS_URL` env var → all engagements share `localhost:6379`.
- **Fix:** Remove the default or raise a clear configuration error if `REDIS_URL` is not set.

---

## BUG 26 [DEAD-CODE] — Comment says "max of local + Redis" but code uses `max()`, not `sum()`
- **File:** `utils.py` lines 73–85
- **Bug Type:** documentation
- **Description:** The docstring says "Get total cost spent so far (max of local + Redis)" which is ambiguous. The code uses `max(self._local_spend, redis_cost)` — it takes the larger of the two, not the sum. This is intentional (double-counting prevention) but the docstring is misleading.
- **Fix:** Update docstring to: "Get total cost spent so far (maximum of local and Redis values to avoid double-counting across workers)".

---

## BUG 27 [RACE] — `run_analysis` TOCTOU: early-return check vs state machine init
- **File:** `analyze.py` lines 22–25
- **Bug Type:** race
- **Description:** `run_analysis()` calls `_get_engagement_state()` (line 22) and returns early if state is not `"analyzing"`. Then `task_context` at line 33 initializes the state machine with `current_state="analyzing"`. Between the check and the state machine init, another worker could have set the state to `"analyzing"` (after we decided to skip), or could have moved it away from `"analyzing"` (to `"failed"`, `"complete"`, etc.) causing the state machine to have a stale `current_state`. The DB-level `FOR UPDATE` locking in `_persist_state_and_budget` mitigates this partially, but the pre-check is misleading and adds a TOCTOU window without benefit.
- **Reproduction Path:** Tight timing between two workers on the same engagement.
- **Fix:** Remove the early-return pre-check and let the state machine handle idempotency. Or move the check inside the `with task_context()` block so it's closer to the actual transition.

---

## BUG 28 [DATA-INTEGRITY] — No finding limit per engagement
- **File:** `database/repositories/finding_repository.py` (all creation methods)
- **Bug Type:** data-integrity
- **Description:** There is no limit on the number of findings per engagement. `create_finding()` and `upsert_secret_finding()` create findings without checking a cap. With aggressive scanning, an engagement could accumulate millions of findings, causing unbounded storage growth, slow queries, and report generation timeouts. The `find_unreviewed_low_confidence` query uses `LIMIT %s` but that only caps the query result, not storage.
- **Reproduction Path:** Run a scan that generates excessive findings → storage grows unboundedly.
- **Fix:** Add a configurable `MAX_FINDINGS_PER_ENGAGEMENT` constant and check it before INSERT. Alternatively, enforce at the DB level with a trigger or application-level check in `create_finding()`.

---

## BUG 29 [DATA-INTEGRITY] — Batch findings insert in `tool_executor.py` lacks `source_tool IS NULL` legacy handling
- **File:** `tools/tool_executor.py` lines 275–304 (referenced by conflict pattern)
- **Bug Type:** data-integrity
- **Description:** The batch `execute_values` path uses `ON CONFLICT (engagement_id, endpoint, type, source_tool) DO UPDATE SET` but does **not** have the `source_tool = source_tool or ""` guard present in `finding_repository.py:67`. If any row in the batch has `source_tool = NULL`, the conflict key becomes `(..., NULL)` which is a different key from `(..., "")`. This creates duplicate findings: one row with `source_tool IS NULL` and one with `source_tool = ""`. It also skips the legacy migration logic (updating NULL rows to non-NULL).
- **Reproduction Path:** A tool run passes findings with explicit `None` as `source_tool` → batch insert creates duplicate rows.
- **Fix:** Coerce `source_tool` to empty string in every row before batch insert, matching the pattern in `finding_repository.py`.

---

---

## Summary

| Bug # | Type | Severity | File | Line(s) |
|-------|------|----------|------|---------|
| 1 | data-loss | **CRITICAL** | recon.py | 58–83 |
| 2 | logic | **HIGH** | recon.py / scan.py | 127–138 / 37 |
| 3 | dead-code | MEDIUM | analyze.py | 91–99 |
| 4 | race | **HIGH** | recon.py | 58–83 |
| 5 | dead-code | LOW | report.py | 154 |
| 6 | dead-code | MEDIUM | llm_review.py | 126–131 |
| 7 | dead-code | MEDIUM | llm_review.py | 153, 244 |
| 8 | resource-leak | **HIGH** | asset_discovery.py | 113–128 |
| 9 | logic | **HIGH** | utils.py | 149–170 |
| 10 | security | MEDIUM | llm_review.py | 255–291 |
| 11 | silent-failure | LOW | scan.py | 47–48 |
| 12 | race | LOW | analyze.py | 22–25 |
| 13 | logic | MEDIUM | analyze.py | 85–90 |
| 14 | data-integrity | MEDIUM | report.py | 401–417 |
| 15 | race/performance | MEDIUM | finding_repository.py | 543–565 |
| 16 | silent-failure | LOW | utils.py | 84 |
| 17 | logic | MEDIUM | diff.py | 84 |
| 18 | documentation | LOW | recon.py | 140 |
| 19 | logic | MEDIUM | scan.py | 77–80, 88–90 |
| 20 | data-loss | **HIGH** | asset_discovery.py | 123–128 |
| 22 | race | LOW | report.py | 40–47 |
| 23 | performance | LOW | utils.py | 88–134 |
| 24 | logic | LOW | llm_review.py | 280 |
| 25 | security | MEDIUM | multiple files | multiple |
| 26 | documentation | LOW | utils.py | 73–85 |
| 27 | race | LOW | analyze.py | 22–25 |
| 28 | data-integrity | MEDIUM | finding_repository.py | all create methods |
| 29 | data-integrity | MEDIUM | tool_executor.py | 275–304 |

### Top 5 Most Critical Fixes (in priority order):
1. **Bug 1** — Recon context never saved; scan always runs blind
2. **Bug 8 + Bug 20** — Connection leak + uncommitted transaction in asset_discovery
3. **Bug 9** — Implicit None return causes crash in downstream callers
4. **Bug 4** — Race: scan receives stale engagement state
5. **Bug 13** — Empty/invalid actions incorrectly fail the engagement
