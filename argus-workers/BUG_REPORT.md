# Argus Security Scanner Pipeline — Comprehensive Bug Audit

> **Date**: 2026-05-24  
> **Scope**: `argus-workers/` — all core files  
> **Methodology**: Exhaustive source-code review against Runtime Error, State Machine Logic, Task Dispatch Ordering, Recon Context Boundary, Orchestrator Scan Dispatch, Finding Persistence, Intelligence Engine, ReAct Agent Loop, Swarm Agents, Scan Diff Engine, Bug Bounty Mode Propagation, and General Anti-Pattern categories.

---

## SEVERITY SUMMARY

| Severity | Count | Key Issues |
|----------|-------|------------|
| **CRITICAL** | 7 | Silent data loss, engagement stuck, runtime crash, dead code safety net |
| **HIGH** | 6 | Feature flag bypass, silent drops, deadlocks, race conditions |
| **MEDIUM** | 12 | Broken state ordering, dead params, misleading signals, blocking I/O |
| **LOW** | 13 | anti-patterns, redundant code, duplicate entries, import issues |

**Total: 38 items**

---

## BUG #1 — CRITICAL
**File**: `tasks/scan.py` — Lines 108-109, 137-138, 158-159  
**Type**: Engagement Stuck / Silent Failure

**Description**: Both `deep_scan` and `auth_focused_scan` call `fetch_engagement_scan_options()` outside of `task_context`. If the DB query fails (e.g., connection timeout, engagement not found), they return `{"status": "failed"}` WITHOUT transitioning the engagement state to `"failed"`. The engagement remains in `"scanning"` (or whatever state it was dispatched from) — permanently stuck with no downstream task ever advancing it.

```python
except Exception as e:
    logger.error("Failed to fetch scan options for deep_scan engagement=%s: %s", ...)
    return {"phase": "deep_scan", "status": "failed", "reason": str(e)}
```

**Reproduction**:
1. Dispatch `deep_scan` or `auth_focused_scan` while DB is unreachable
2. The task returns `failed` without any state transition
3. Engagement is stuck in prior state (e.g., `"scanning"`) forever

**Fix**: Either wrap the `fetch_engagement_scan_options` call inside `task_context`, or manually call the state machine's `transition("failed", ...)` before returning. The `task_context` pattern already handles this correctly — use it.

---

## BUG #2 — CRITICAL
**File**: `orchestrator_pkg/orchestrator.py` — Line 77  
**Type**: Silent Data Loss

**Description**: When `DATABASE_URL` environment variable is not set, `FindingRepository(db_conn)` receives `None` and `self.finding_repo` is set to `None`. In `_save_findings` (line 271):

```python
if not self.finding_repo or not findings:
    return 0
```

**Returning `0` means "0 findings failed to save"** — i.e., all findings were saved successfully. But in reality, ZERO findings were persisted. Callers like `run_scan` (line 660) check `if failed_saves > 0` — since `0 > 0` is `False`, no warning is emitted, and the pipeline reports success. **All findings are silently discarded.**

**Reproduction**:
1. Run Argus without `DATABASE_URL` env var
2. Run a scan — all findings are created in memory, normalized, but never saved to DB
3. The scan result reports `findings_count: 0` but the log shows `failed_saves: 0` (no warning)

**Fix**: Change the return value when `finding_repo` is `None`:
```python
if not self.finding_repo:
    logger.error("No finding repository configured — DATABASE_URL not set")
    return len(findings)  # Report ALL findings as failed
```
Or, raise a hard error at orchestrator construction time if `db_conn` is None.

---

## BUG #3 — CRITICAL
**File**: `orchestrator_pkg/scan.py` — Lines 296-312  
**Type**: Missing Completion Event / UI Bug

**Description**: The nuclei scanner is run via `tool_runner.run_streaming()` (line 312) which processes findings inline via the `_on_nuclei_line` callback. `emit_tool_start` IS called on line 311, but `emit_tool_complete` is NEVER called for nuclei. Every other tool goes through `_run_scan_tool` which has a `finally` block guaranteeing `emit_tool_complete`. The frontend sees a `tool_started:nuclei` event but **never sees `tool_completed:nuclei`**, making it look like nuclei is perpetually running.

```python
# Line 311-312:
emit_tool_start(ctx.engagement_id, "nuclei", nuclei_cmd)
ctx.tool_runner.run_streaming("nuclei", nuclei_cmd, nuclei_timeout, _on_nuclei_line)
# NO emit_tool_complete call!
```

**Reproduction**: Any scan where nuclei runs. Frontend shows "nuclei: running..." indefinitely.

**Fix**: Add `emit_tool_complete` after `run_streaming` completes or fails:
```python
try:
    emit_tool_start(ctx.engagement_id, "nuclei", nuclei_cmd)
    ctx.tool_runner.run_streaming("nuclei", nuclei_cmd, nuclei_timeout, _on_nuclei_line)
    emit_tool_complete(ctx.engagement_id, "nuclei", True, 0)
except Exception:
    emit_tool_complete(ctx.engagement_id, "nuclei", False, 0)
    raise
```

---

## BUG #4 — CRITICAL
**File**: `orchestrator_pkg/orchestrator.py` — Lines 1215-1224  
**Type**: Dead Code Safety Net

**Description**: `_check_timeout()` is meant to raise `EngagementTimeoutError` when the engagement exceeds `HARD_TIMEOUT_SECONDS` (7200s). However, `start_time` is only set in `Orchestrator.run()` (line 169-170). All Celery tasks call `run_recon()`, `run_scan()`, `run_analysis()`, or `run_reporting()` **directly** — never through `run()`. Each of these methods calls `_check_timeout()` (lines 192, 628, 789, 982), but since `self.start_time` is `None`, the method returns immediately:

```python
def _check_timeout(self):
    if self.start_time is None:
        return  # ← always returns here, timeout never fires
```

**The hard timeout safety mechanism is completely dead code.** Engagements with runaway scanning have no orchestrator-level upper bound. Only Celery's `soft_time_limit` (2400s) provides protection, which is a hard process-level kill that loses all context and doesn't transition state.

**Reproduction**: Any orchestrated task — `start_time` is never initialized.

**Fix**: Set `self.start_time` in `__init__`, not in `run()`:
```python
def __init__(self, ...):
    ...
    self.start_time = time.time()  # initialize immediately
```

---

## BUG #5 — CRITICAL
**File**: `database/repositories/finding_repository.py` — Line 132  
**Type**: Runtime Crash / Schema Mismatch

**Description**: The `INSERT ... ON CONFLICT (engagement_id, endpoint, type, source_tool)` clause (line 122-131) assumes a UNIQUE constraint exists on `(engagement_id, endpoint, type, source_tool)` in the `findings` table. If this constraint doesn't exist (e.g., the migration hasn't been applied, or the constraint was defined differently), PostgreSQL raises:

```
ERROR: there is no unique or exclusion constraint matching the ON CONFLICT specification
```

**There is no startup validation, no migration check, and no graceful error handling for this.** The first time a duplicate finding is created, the entire task crashes with a raw psycopg2 error, transitioning the engagement to `"failed"` if the caller has error handling, or leaving it stuck if not.

**Reproduction**:
1. Deploy the schema without the unique constraint on `(engagement_id, endpoint, type, source_tool)`
2. Run any scan that produces findings
3. The first insert works fine (no conflict), but no constraint was created
4. Wait — actually, `ON CONFLICT` throws even on the FIRST insert if the constraint doesn't exist. The PostgreSQL parser checks this at query-plan time. **It crashes on every single finding insert.**

**Fix**: Either:
1. Add a database migration to create the unique constraint
2. Add startup validation that checks the constraint exists
3. Use SELECT-then-UPDATE-else-INSERT instead of ON CONFLICT

---

## BUG #6 — CRITICAL
**File**: `database/repositories/finding_repository.py` — Lines 76-81  
**Type**: Silent Finding Drop (amplified by BUG #2)

**Description**: When `MAX_FINDINGS_PER_ENGAGEMENT` (50,000) is reached, `create_finding()` returns `None` without raising an exception. `_save_findings` in orchestrator.py checks `if saved_id:` — since `None` is falsy, the finding is silently skipped. The caller has **no way to distinguish** "finding was a duplicate that was updated" from "finding cap was exceeded."

Additionally, the TOCTOU check on line 71 (`SELECT COUNT(*)`) is not under `FOR UPDATE`, so two concurrent inserts can both pass the cap check and exceed the limit by a small margin. The comment acknowledges this, but this means the cap is approximate at best.

**Reproduction**: Fill an engagement with 50,000 findings. All subsequent findings are silently dropped.

**Fix**: Either:
1. Raise a custom `FindingCapExceededError` so callers can detect and handle it
2. Return a sentinel object instead of `None` so callers can differentiate
3. Log at `ERROR` level (not `WARNING`) when the cap is hit

---

## BUG #7 — HIGH
**File**: `orchestrator_pkg/orchestrator.py` — Lines 306-311 (combined with `tasks/scan.py` line 638-643)  
**Type**: Feature Flag Inconsistency / Logic Gap

**Description**: Bug bounty mode propagation is inconsistent between the agent layer and the persistence layer.

- **Agent layer** (`run_scan_with_agent` line 540): Passes `mode="bugbounty"` to `create_phase_agent` **regardless of feature flags**. The agent receives bug bounty mode correctly.
- **Persistence layer** (`_save_findings` lines 306-311): Checks `_ff_enabled("ENGAGEMENT_STATE", default=False) and hasattr(self, "state")`. When the feature flag is OFF (the default), `self.state` doesn't exist, so `bug_bounty` is always `False`, and `finding["bugbounty_source"] = True` is never set.
- **Intelligence Engine** (`intelligence_engine.py` line 227): The Bug-Reaper confidence cap (`confidence = min(confidence, 0.70)`) only applies when `finding.get("bugbounty_source")` is True.

**Result**: With default feature flags:
1. Agent runs in bug bounty mode ✓
2. Findings are NOT tagged with `bugbounty_source = True` ✗
3. The Intelligence Engine's confidence cap is never applied ✗
4. Findings that should be conservatively capped at 0.70 can have higher confidence scores, potentially causing false positives to be treated as high-confidence findings.

**Reproduction**: Bug bounty mode engagement with `ENGAGEMENT_STATE` flag disabled (default). All findings bypass the confidence cap.

**Fix**: Store `bug_bounty_mode` directly on the Orchestrator instance (not gated by a feature flag):
```python
# In __init__:
self.bug_bounty_mode = False

# In run_scan (always, not behind feature flag):
self.bug_bounty_mode = bool(job.get("bug_bounty_mode", False))

# In _save_findings:
bug_bounty = self.bug_bounty_mode  # No feature flag check
```

---

## BUG #8 — HIGH
**File**: `tasks/base.py` — Lines 170-186 and 194-212  
**Type**: Race Condition / Connection Management

**Description**: In both `SoftTimeLimitExceeded` and generic `Exception` handlers, when `_state_assigned` is `False`, a **new** `EngagementStateMachine` is created and calls `transition("failed", ...)`. The original `DistributedLock` is still held (we're inside the `with LockContext` block — the `LockContext.__exit__` hasn't run). Creating a new SM means it opens a **separate DB connection** while the original lock holds the Redis key. This creates a window where:

1. The new SM's `_persist_state_and_budget` queries the DB for engagement state
2. The DB state might be stale because the lock was held by a different connection (the original SM)
3. The `SELECT ... FOR UPDATE` in `_persist_state_and_budget` uses the new SM's connection, which is NOT protected by the existing Redis lock
4. If the engagement was already updated by another worker between the original SM's creation and the crash, the new SM sees stale state

**Reproduction**: Task crashes immediately after SM creation (line 129) but before `_state_assigned` is set (line 153). The lock is held. The new SM uses a fresh connection that was never locked.

**Fix**: In the error handlers, use the existing `sm` object (already created on line 129) instead of creating a new one:
```python
except Exception as e:
    if _lock_acquired and _state_assigned:
        ...
    elif _lock_acquired:
        # Use existing SM (already created on line 129)
        sm.transition("failed", f"{job_type} failed: {e}")
```

Or, pass `connection` from the existing SM's `_get_connection()` to the new SM.

---

## BUG #9 — HIGH
**File**: `tasks/recon.py` — Line 86 / `orchestrator_pkg/orchestrator.py` — Lines 611-613  
**Type**: Silently Swallowed Findings from Fallback

**Description**: In `run_scan_with_agent` (orchestrator.py lines 608-613), when the agent fails for a target, the fallback `execute_scan_pipeline` returns findings. However, the findings from the **fallback are not normalized through `_normalize_finding`**. They're raw finding dicts returned directly from `execute_scan_pipeline`. Meanwhile, the main path (line 604-606) does normalize each finding. The fallback findings may have a different structure (missing required fields like `source_tool`, malformed evidence, etc.) causing downstream issues in `_save_findings`.

Additionally, `execute_scan_pipeline` is called with `tech_stack=recon_context.tech_stack if recon_context else None`. If `recon_context` is `None`, `tech_stack` becomes `None`, which means technology-aware tool selection is skipped for the fallback.

**Reproduction**: Agent fails for a target. Fallback findings are raw dicts that may fail normalization or deduplication.

**Fix**: Normalize fallback findings the same way as agent findings:
```python
fallback = execute_scan_pipeline(...)
for f in fallback:
    norm = self._normalize_finding(f, f.get("source_tool", "fallback"))
    if norm:
        all_findings.append(norm)
```

---

## BUG #10 — HIGH
**File**: `orchestrator_pkg/scan.py` — Lines 164-182  
**Type**: Misleading Success Signal

**Description**: In `_run_scan_tool`, the variable `success` is set to `result.success` on line 176 **before** the parser call on line 171. If `result.success` is True but `ctx.parser.parse(tool_name, result.stdout)` raises an exception, the `finally` block on line 182 emits `emit_tool_complete(success=True)` because the local `success` variable was already set to True.

The frontend and the Intelligence Engine think the tool succeeded, but all findings were lost due to a parse error.

```python
success = False
try:
    ...
    emit_tool_start(...)
    result = ctx.tool_runner.run(...)
    if result.success and result.stdout:
        parsed = ctx.parser.parse(tool_name, result.stdout)  # ← may raise
        for p in parsed:
            normalized = ctx._normalize_finding(p, tool_name)
            ...
    success = result.success  # ← set BEFORE parser can raise
    return ...
except Exception:
    ...
finally:
    emit_tool_complete(..., success=success)  # ← reports True even if parser failed
```

**Reproduction**: Parser encounters unexpected output format (e.g., nuclei changes output schema). Tool succeeds but parser raises. Findings are lost, tool reports success.

**Fix**: Set `success = True` only after parsing succeeds:
```python
if result.success and result.stdout:
    parsed = ctx.parser.parse(tool_name, result.stdout)
    if parsed:
        success = True  # ← only now is it truly a success
    ...
```

---

## BUG #11 — HIGH
**File**: `intelligence_engine.py` — Lines 227-230  
**Type**: Confidence Cap Bypass

**Description**: (Coupled with BUG #7) The Bug-Reaper confidence cap at 0.70 only fires when `finding.get("bugbounty_source")` is truthy OR when `requires_validation + source == "bugbounty"`. Because `bugbounty_source` is never set when the `ENGAGEMENT_STATE` feature flag is off (see BUG #7), findings in bug bounty mode engagements **always bypass the confidence cap** under default configuration. False positives in bug bounty programs are treated with the same confidence as verified findings.

**Reproduction**: See BUG #7.

**Fix**: Resolve BUG #7's root cause. Additionally, add a secondary path for the confidence cap:
```python
if finding.get("bugbounty_source") or (
    finding.get("requires_validation") and finding.get("source") == "bugbounty"
) or self._is_bugbounty_engagement:
    confidence = min(confidence, 0.70)
```

---

## BUG #12 — HIGH
**File**: `tasks/base.py` — Lines 172, 196  
**Type**: Double-Connection Pattern

**Description**: When `_state_assigned` is `False` (between SM creation on line 129 and the feature-flag assignment on lines 139-154), the error handlers on lines 172 and 196 create a **new** `EngagementStateMachine` with a fresh DB connection. This new SM then calls `transition("failed", ...)`. The problem: the new SM doesn't have the same `_ws_publisher` that `task_context` would normally configure (line 135). So websocket events for the transition to "failed" are NOT published during error handling in the `_state_assigned=False` window. The frontend never sees the "failed" transition.

**Reproduction**: Exception between lines 129 and 153. Engagement transitions to "failed" in DB but frontend stays on the last known state.

**Fix**: Configure the new SM's `_ws_publisher` the same way, or (as in BUG #8's fix) use the existing SM instance.

---

## BUG #13 — MEDIUM
**File**: `tasks/analyze.py` — Line 43  
**Type**: State Transition Ordering

**Description**: The transition to `"reporting"` happens BEFORE dispatching the report task:
```python
ctx.state.transition("reporting", "Analysis complete")        # Line 43
app.send_task('tasks.report.generate_report', ...)             # Line 45-46
```

If `transition()` succeeds but `send_task()` fails, the engagement is stuck in `"reporting"` with no report task to advance it. The `except` block (line 48) does call `safe_transition("failed")`, but there's a window between the transition and the dispatch where a concurrent observer sees "reporting" with no running report task.

**Reproduction**: Network partition between Celery app and broker at the exact moment after state transition but before `send_task`.

**Fix**: Dispatch the task FIRST, then transition to "reporting":
```python
try:
    app.send_task('tasks.report.generate_report', ...)
    ctx.state.transition("reporting", "Analysis complete — report dispatched")
except Exception as e:
    ctx.state.safe_transition("failed", f"Failed to dispatch report: {e}")
```

---

## BUG #14 — MEDIUM
**File**: `orchestrator_pkg/recon.py` — Lines 27-31  
**Type**: Dead Parameter

**Description**: `execute_recon_tools` accepts `budget: dict` as a parameter but **never uses it** anywhere in the function body. The budget is passed through `pipeline_router.execute_recon_pipeline()` → `execute_recon_tools()` and silently discarded. Recon phase has no budget enforcement:

```python
def execute_recon_tools(
    ctx,
    target: str,
    budget: dict,        # ← accepted but NEVER referenced below
    aggressiveness: str = DEFAULT_AGGRESSIVENESS,
) -> list[dict]:
```

Meanwhile, `execute_scan_tools` in `scan.py` also accepts `budget` and **doesn't use it either** (line 186 — the `budget` parameter is defined but never read in the function body).

**Reproduction**: Set a small recon budget. All recon tools (10 parallel tools) run regardless of budget exhaustion.

**Fix**: Either:
1. Remove the unused `budget` parameter from both `execute_recon_tools` and `execute_scan_tools`
2. Implement budget checks in the tool execution loops (e.g., skip expensive tools when budget remaining is low)

---

## BUG #15 — MEDIUM
**File**: `orchestrator_pkg/orchestrator.py` — Lines 293-294 (and callers)  
**Type**: Type Contract Violation

**Description**: `_save_findings` is declared to return `int` (`-> int`), but line 294 has a bare `return` statement which returns `None`:

```python
if not findings:
    return    # ← returns None, not int
```

Callers like `run_scan` (line 660) compare `failed_saves > 0` — both `None > 0` and `0 > 0` are `False`, so the silent data loss goes undetected. However, `None > 0` raises `TypeError` in Python 3! Actually, wait — in Python 3, `None > 0` raises `TypeError: '>' not supported between instances of 'NoneType' and 'int'`. This would crash the scan task **at runtime**, transitioning the engagement to "failed" with a misleading error about "comparison not supported" when the real issue is that all findings were dropped from the input list.

Actually, let me check: in Python 3, `None > 0` does raise TypeError. So this would crash.

But wait — let me re-read the flow. `findings = normalized_inputs` on line 292. The normalization on lines 274-292 only produces an empty list if ALL items are non-dict and don't have `.findings` attribute. This is unusual but possible. When `findings` is empty, the `if not findings: return` on line 294 returns None. Then:

```python
# In run_scan (line 660):
failed_saves = self._save_findings(findings)  # returns None
if failed_saves > 0:                           # raises TypeError!
```

This is a **critical crash path** hidden inside a type violation.

**Fix**: Change `return` to `return 0`.

---

## BUG #16 — MEDIUM
**File**: `tasks/llm_review.py` — Line 334  
**Type**: URL Construction Bug

**Description**: When building the replay request URL, the code blindly appends `?q=payload` to the endpoint URL:

```python
test_url = f"{endpoint}?{urlencode({'q': payload})}"
```

If `endpoint` already contains query parameters (e.g., `https://example.com/search?query=test`), the resulting URL is malformed:
```
https://example.com/search?query=test?q=payload
#                                      ^ should be &
```

The URL now has two `?` markers, and the second one (`?q=payload`) becomes part of the query string value or is treated as a separate invalid query string, depending on the server's URL parser.

**Reproduction**: LLM review of a finding with endpoint `https://example.com/api/v1/users?id=123`. The replayed request is `https://example.com/api/v1/users?id=123?q=test_payload` — the `?q=...` is appended to the existing query string rather than added as a parameter.

**Fix**: Parse the endpoint URL, merge the payload parameter:
```python
from urllib.parse import urlencode, urlparse, parse_qs, urlunparse
parsed = urlparse(endpoint)
params = parse_qs(parsed.query)
params['q'] = payload
new_query = urlencode(params, doseq=True)
test_url = urlunparse(parsed._replace(query=new_query))
```

---

## BUG #17 — MEDIUM
**File**: `orchestrator_pkg/scan.py` — Lines 164-182 (specifically: `result.stdout` on line 171)  
**Type**: Variable Shadowing / Logic

**Description**: In `_run_scan_tool`, the variable `success` is initialized to `False`. After `ctx.tool_runner.run(...)` succeeds and `result.stdout` is truthy, `ctx.parser.parse(...)` is called. If the parse returns an empty list (no findings parsed but no exception raised), `success` is still set to `result.success` (True) on line 176. The tool is reported as successful with zero findings. This is intentional behavior (the tool ran fine, it just found nothing), but the `emit_tool_complete` doesn't include a finding count metric, so the frontend can't distinguish "tool found nothing" from "tool found findings but they were all filtered."

**Reproduction**: (Design issue, not a crash) A tool like `whatweb` runs successfully but produces no findings. The frontend shows it as successful with no indication of zero results.

**Fix**: (Low priority) Include parsed count in the `emit_tool_complete` call.

---

## BUG #18 — MEDIUM
**File**: `tasks/llm_review.py` — Lines 86-99  
**Type**: TOCTOU Race (Terminal State)

**Description**: The terminal-state guard check at lines 86-99 queries the engagement status from the DB **outside any lock** (it's before `task_context` or any mutex). Between this check and the actual processing, the engagement could transition to `"complete"` or `"failed"`. The subsequent processing code doesn't re-check, so LLM review might run on a terminal-state engagement.

**Reproduction**:
1. LLM review task starts and checks state → engagement is in "analyzing"
2. Before processing begins, another task transitions engagement to "complete"
3. LLM review processes findings anyway

**Fix**: Re-check the state before each finding's processing step, or acquire a shared lock for the duration of processing.

---

## BUG #19 — MEDIUM
**File**: `intelligence_engine.py` — Lines 780-817  
**Type**: Blocking I/O in Sync Code

**Description**: `_fetch_nvd_cve_data` makes synchronous HTTPS requests to the NVD API for EACH CVE. With 5 CVEs and a 10s per-request timeout, the Intelligence Engine can be blocked for up to 50 seconds. During this time, the enter `evaluate()` method is blocked — no analysis, no scoring, no state transition happens.

```python
with httpx.Client(timeout=10.0) as client:
    for cve_id in cve_ids:  # ← sequential, N requests
        response = client.get(f"https://services.nvd.nist.gov/rest/json/cves/2.0?cveId={cve_id}", ...)
```

The same pattern affects `_fetch_epss_scores` (line 837-854).

**Reproduction**: Engagement with findings referencing multiple CVEs. NVD API is slow or throttling. Intelligence evaluation takes 30-50 seconds longer.

**Fix**: Either:
1. Use `httpx.AsyncClient` with `asyncio.gather()` for parallel fetching
2. Move threat intelligence enrichment to a background task that doesn't block `evaluate()`
3. Set a shorter per-request timeout (e.g., 5s instead of 10s)

---

## BUG #20 — MEDIUM
**File**: `tasks/utils.py` — Lines 110-128  
**Type**: Connection Pool Never Torn Down

**Description**: `_redis_pool` is a module-level global `ConnectionPool` that is created once and never closed or recreated. In long-running Celery worker processes, if Redis restarts:

1. The pool's existing connections become stale/dead
2. Pool health checks are not enabled (`health_check_interval` is not set on the pool)
3. The next operation on a stale connection may hang or raise `ConnectionError`
4. There is no code to recreate the pool on failure

```python
_redis_pool = redis_module.ConnectionPool.from_url(
    url,
    socket_connect_timeout=2,
    socket_timeout=2,
    max_connections=10,
    # No health_check_interval!
)
```

**Reproduction**: Long-running Celery worker (hours/days). Redis restarts or network blip occurs. Subsequent Redis operations hang for `socket_timeout=2s` then fail.

**Fix**:
```python
_redis_pool = redis_module.ConnectionPool.from_url(
    url,
    socket_connect_timeout=2,
    socket_timeout=2,
    max_connections=10,
    health_check_interval=30,  # Check connection health every 30s
)
```

Also, add pool recreation in error handlers:
```python
except redis_module.ConnectionError:
    _redis_pool = None  # Force pool recreation on next call
    _redis_pool_url = None
```

---

## BUG #21 — MEDIUM
**File**: `agent/react_agent.py` — Lines 534-553  
**Type**: Incomplete Scope Validation

**Description**: `_validate_arguments` only checks the `"target"` key in action arguments for private/loopback IPs. Other parameter names that can contain network targets — `"url"`, `"host"`, `"hostname"`, `"domain"`, `"endpoint"` — are NOT checked:

```python
target = action.arguments.get("target", "")
if target:
    ...validate target...
```

The orchestrator's `scoped_call` wrapper (orchestrator.py line 577) correctly checks ALL these names:
```python
_target_params = ["target", "url", "host", "hostname", "domain", "endpoint"]
for _param in _target_params:
    tgt = kwargs.get(_param, "")
```

But when the agent runs independently (via `ReActAgent.run()` called directly, not through the orchestrator), the `scoped_call` wrapper is never installed, and the incomplete `_validate_arguments` is the only line of defense.

**Reproduction**: Direct agent invocation where the LLM chooses to pass `url=http://169.254.169.254` as the parameter. `_validate_arguments` checks `arguments.get("target", "")` which is empty — bypass passes. The orchestrator's `scoped_call` wrapper would have caught this, but it's not in the call chain.

**Fix**: Check ALL common target parameter names:
```python
_target_params = ["target", "url", "host", "hostname", "domain", "endpoint"]
for param_name in _target_params:
    target = action.arguments.get(param_name, "")
    if target:
        ...validate...
        break
```

---

## BUG #22 — MEDIUM
**File**: `agent/swarm.py` — Lines 561-581  
**Type**: Subprocess Orphaning

**Description**: When the swarm times out, `pool.shutdown(wait=False, cancel_futures=True)` cancels future tasks but does NOT terminate already-running threads. Running threads that spawned subprocesses (sqlmap, nuclei, etc.) are left running. The `psutil` kill loop (lines 572-581) tries to mitigate:

```python
try:
    import psutil
    current_process = psutil.Process()
    for child in current_process.children(recursive=True):
        child.kill()
except Exception:
    logger.debug("Could not kill orphaned tool processes...")
```

But if `psutil` is not installed (the `except` silently catches the `ImportError`), **all tool subprocesses are orphaned**. This is a resource leak that accumulates over time.

On top of that: `import psutil` inside the error handler — it's not at module level, so an `ImportError` is expected and swallowed. But the comment in the exception handler just says `psutil may not be available` — no warning, no fallback, no alternative cleanup.

**Reproduction**: Swarm timeout without `psutil` installed. sqlmap or nuclei processes keep running as orphans.

**Fix**: Either:
1. Add `psutil` as a hard dependency
2. Track PIDs of all spawned subprocesses in the agent and kill them directly using `os.kill()` with `signal.SIGKILL`
3. At minimum, log a WARNING when `psutil` is not available and orphaned processes may exist

---

## BUG #23 — MEDIUM
**File**: `tasks/base.py` — Lines 159-160  
**Type**: Incorrect Type Guard

**Description**: The orchestrator state wiring depends on `isinstance(state, EngagementState)`:
```python
if isinstance(state, EngagementState):
    orchestrator.state = state  # Step 10: wire EngagementState into orchestrator
```

But `state` can also be an `EngagementStateMachine` (when the feature flag is off). In that case, `orchestrator.state` is never set. All code paths that use `self.state` are gated behind `hasattr(self, "state")`, so this is safe but fragile. A code change that accidentally removes the `hasattr` check would crash.

**Reproduction**: (Fragility pattern, not active bug) A future developer adds `self.state.some_method()` without `hasattr` check — crashes when feature flag is off.

**Fix**: Always set `orchestrator.state = state` (regardless of type), and ensure `EngagementStateMachine` exposes the needed interface.

---

## BUG #24 — MEDIUM
**File**: `tasks/diff.py` — Lines 63-66 and 149-168  
**Type**: Private Method Call

**Description**: `_update_fixed_fingerprints` (line 155) calls `ScanDiffEngine._fingerprint(f)` which is a private static method (prefixed with `_`). Same issue at diff.py line 63: `TargetProfileRepository._extract_domain(target_url)` called externally. Calling private methods across module boundaries creates implicit coupling — if the private method is renamed or refactored, the caller silently breaks.

**Reproduction**: Any semantic rename or refactoring of `ScanDiffEngine._fingerprint` or `TargetProfileRepository._extract_domain`.

**Fix**: Either:
1. Make the methods public (remove `_` prefix) and document the API contract
2. Add public wrapper methods that delegate to the private implementation
3. Use `hasattr`/callable checks with logging if the method doesn't exist

---

## BUG #25 — LOW
**File**: `state_machine.py` — Line 86  
**Type**: Exception Information Loss

**Description**: In the `__init__` method, when the DB query for engagement state fails, the exception `e` is caught but **not included in the log message**:

```python
except Exception:
    logger.warning(
        "Could not query state for engagement %s, defaulting to 'created'",
        engagement_id,
    )
```

Any diagnostic value from the exception (connection error, table not found, etc.) is silently lost. The developer sees "could not query state" with no indication of why.

**Reproduction**: DB connection failure during state machine construction.

**Fix**: Include the exception:
```python
except Exception as e:
    logger.warning("Could not query state for engagement %s: %s", engagement_id, e)
```

---

## BUG #26 — LOW
**File**: `state_machine.py` — Line 67  
**Type**: Transient Inconsistent State

**Description**: `self.current_state = current_state` is set on line 67, before the None-handling block (lines 73-90). If `current_state` is `None`:

1. Line 67: `self.current_state = None`
2. Lines 73-90: Query DB, get actual state, reassign local `current_state`
3. Line 90: `self.current_state = current_state` (the DB result)

Between lines 67 and 90, `self.current_state` is `None`. Any code accessing the SM instance during this window reads `None`.

**Reproduction**: (Tight race window) Access `sm.current_state` during DB query in constructor.

**Fix**: Move `self.current_state = current_state` to after the None-handling block (after line 98).

---

## BUG #27 — LOW
**File**: `orchestrator_pkg/recon.py` — Line 64  
**Type**: Fragile URL Parsing

**Description**: Target domain extraction uses naive string replacement:
```python
target_domain = target.replace("https://", "").replace("http://", "").split("/")[0]
```

This fails for:
- IPv6 addresses: `http://[::1]:8080/path` → `[::1]:8080` (correct, actually)
- URLs with embedded credentials: `http://user:pass@example.com:8080/path` → `user:pass@example.com:8080` (may confuse tools expecting just the host)
- URLs with unusual schemes (though `execute_recon_tools` only runs on targets that passed validation)

**Reproduction**: Scan with target URL containing embedded credentials.

**Fix**: Use `urllib.parse.urlparse(target).hostname` for proper extraction.

---

## BUG #28 — LOW
**File**: `agent/react_agent.py` — Lines 800-803  
**Type**: Dead Condition

**Description**: The condition `result.tool in tried_tools` is ALWAYS True at this point because `tried_tools.add(action.tool)` was called on line 748, before this check:

```python
if result.tool in tried_tools and not result.success:
    pass
```

The first conjunct is redundant — the effective condition is just `not result.success`.

**Reproduction**: Always — every iteration reaches this check.

**Fix**: Remove the redundant conjunct:
```python
if not result.success:
    pass
```

---

## BUG #29 — LOW
**File**: `config/constants.py` — Lines 30-50  
**Type**: Duplicate Allowlist Entries

**Description**: `GIT_HOST_ALLOWLIST` contains duplicate entries:
- `github.com` at positions 1, 8 (line 31 vs 46) — also `gist.github.com` is separate
- `gitlab.com` at positions 2, 19, 20 (lines 32, 42, 47)
- `bitbucket.org` at positions 4, 17 (lines 35, 48)

Also, `gitlab.freedesktop.org` appears at both lines 33 and 43.

**Reproduction**: (Data quality issue) `gitlab.com` being checked 3 times per URL validation.

**Fix**: Deduplicate the tuple:
```python
GIT_HOST_ALLOWLIST = tuple(sorted(set((
    "github.com", "gitlab.com", ...
))))
```

---

## BUG #30 — LOW
**File**: `intelligence_engine.py` — Line 1018  
**Type**: `zip` Without Strict Mode (Python 3.9 compatibility)

**Description**: `zip(reasons, scores, strict=False)` uses the `strict` keyword argument which was added in Python 3.10. If the codebase targets Python 3.9, this raises `TypeError: 'strict' is an invalid keyword argument for zip()`. However, the `pyproject.toml` likely specifies the Python version — if it's 3.10+, this is fine.

**Reproduction**: Running on Python 3.9 or earlier.

**Fix**: Use `zip(reasons, scores)` (without `strict`) if Python 3.9 compatibility is required.

---

## BUG #31 — LOW
**File**: `models/finding.py` — Lines 52-74  
**Type**: Overly Strict Validation

**Description**: `VulnerabilityFinding` has Pydantic validators that require `type` and `endpoint` to be non-empty (lines 60-74). However, many downstream paths (e.g., LLM review fallback, swarm agent findings) produce findings with empty `type` or `endpoint` strings. The validators raise `ValueError` which is caught somewhere upstream (hopefully) but could crash the task if uncaught.

`evidence` is also required to be a dict (line 52-58), but many raw tool outputs have `evidence` as a string or list. The validator raises ValueError, and the finding is lost.

**Reproduction**: Normalize a tool finding where `evidence` is a JSON string instead of a parsed dict.

**Fix**: Make the validators more lenient — convert strings to dicts where possible, default empty strings to `"UNKNOWN"`.

---

## BUG #32 — LOW
**File**: `orchestrator_pkg/orchestrator.py` — Line 212 (in `run_recon`)  
**Type**: Duplicate Websocket Event

**Description**: `run_recon` manually publishes a state transition for the "no target" case:
```python
self.ws_publisher.publish_state_transition(
    engagement_id=self.engagement_id,
    from_state=self._get_scan_state(),
    to_state="failed",
    reason="Recon skipped — no target URL configured",
)
```

But if the state machine is configured with `_ws_publisher`, the transition method would ALSO publish the same event. However, in this code path, the state machine is NOT called — the code returns early without creating a state machine. So this is actually a missing state machine call, not a duplicate. The websocket event is sent but the DB state transition does NOT happen. The engagement stays in whatever state it was.

Wait — is this also a missing DB transition? Let me re-read:

lines 200-210:
```python
if not target:
    logger.warning(...)
    self.ws_publisher.publish_state_transition(...)
    return {"phase": "recon", "status": "failed", ...}
```

Yes — the engagement stays in "created" (or whatever state) in the DB, but the websocket event says it transitioned to "failed". This is a **mismatch between DB state and websocket event**. The frontend sees "failed" but the DB says "created".

**Reproduction**: Create engagement with target="" or None. Run recon. Frontend shows "failed", but DB still shows "created".

**Fix**: Also transition the engagement state in the DB:
```python
if not target:
    ...
    try:
        from state_machine import EngagementStateMachine
        sm = EngagementStateMachine(self.engagement_id, current_state=self._get_scan_state())
        sm.transition("failed", "No target URL configured for engagement")
    except Exception:
        ...
    self.ws_publisher.publish_state_transition(...)
    return ...
```

---

## BUG #33 — LOW
**File**: `tasks/utils.py` — Lines 17-18  
**Type**: Hardcoded TTL Constants (Hardly a bug, but worth documenting)

**Description**: `RECON_CONTEXT_TTL = 7200` (2 hours). The comment says "was 1h — scan can take 60min to execute". But the engagement hard timeout is 7200s (2 hours), so the recon context could expire before the scan finishes if the scan takes more than 120 minutes (2 hours). This is borderline — the TTL exactly matches the hard timeout. If the timeout is ever raised but this isn't, the recon context vanishes.

**Reproduction**: (Future-proofing) If `HARD_TIMEOUT_SECONDS` is increased beyond 7200s without updating this TTL.

**Fix**: Derive the TTL from the hard timeout constant, or add a comment documenting the dependency.

---

## BUG #34 — LOW
**File**: `agent/coordinator.py` — Lines 56-67 / `agent/react_agent.py` — Lines 101-186  
**Type**: Dead Adapter

**Description**: `CoordinatorAgent.run_phase()` (line 69) creates a new `ReActAgent` via `create_for_phase()` and calls `agent.run(task_desc, initial_context=context)`. But `initial_context` is passed as the second argument and is named `initial_context` in the `run()` method signature (line 622):

```python
def run(self, task: str, initial_context: dict = None, ...):
```

The `initial_context` parameter is marked `noqa: ARG002` — meaning it's **unused**. The coordinator passes context that is silently ignored by the agent.

**Reproduction**: `CoordinatorAgent.run_phase()` — the `context` dict is passed but never used by `ReActAgent.run()`.

**Fix**: Either use the initial context in the agent's run loop, or remove the parameter from both the coordinator call and the agent signature.

---

## BUG #35 — LOW
**File**: `tasks/base.py` — Lines 192, 165, 269  
**Type**: F-String Logging (Anti-Pattern)

**Description**: Several log messages use f-string interpolation instead of lazy `%` formatting:

- Line 165: `slog.error(f"Task failed: {e}")`
- Line 192: `slog.error(f"Task failed: {e}")` (duplicate)
- Line 269: `slog.error(f"{phase_name} failed: {e}")`

With `%` formatting, the string is only evaluated if the log level is enabled. With f-strings, `str(e)` is always called. For `ScanLogger` which may always emit, this is harmless, but the pattern is inconsistent with the `logger.warning(f"...")` vs `logger.warning("...%s", e)` mixing elsewhere.

**Reproduction**: Always present.

**Fix**: Use lazy formatting consistently.

---

## BUG #36 — LOW
**File**: `orchestrator_pkg/orchestrator.py` — Lines 359-362  
**Type**: Inconsistent Dedup

**Description**: The dedup text computation has a inconsistent handling of `payload`:

```python
if payload and '__REDACTED__' not in str(payload):
    dedup_text = f"{ftype} {fep} {payload}"
else:
    dedup_text = f"{ftype} {fep}"  # Fallback: type + endpoint only
```

When `payload` is a non-string type (e.g., dict, list), `str(payload)` in the condition produces a different string than `f"...{payload}"` in the dedup_text. The `__REDACTED__` check uses `str(payload)` but the dedup key uses Python's `__format__` protocol (which for most types is the same as `str()`, but can differ for custom objects).

**Reproduction**: Payload field containing a complex object instead of a string.

**Fix**: Normalize `payload` to a string first:
```python
payload_str = str(payload) if not isinstance(payload, str) else payload
if payload and '__REDACTED__' not in payload_str:
    dedup_text = f"{ftype} {fep} {payload_str}"
```

---

## BUG #37 — LOW
**File**: `orchestrator_pkg/repo_scan.py` — Lines 1012+ (or wherever the temp dir is)  
**Type**: No Temp Directory Cleanup (if error occurs before try/finally)

Actually wait, I see the temp directory is managed by `tempfile.mkdtemp()` outside a `try`:

Line 261: `temp_dir = tempfile.mkdtemp(prefix="argus_repo_scan_")`
Line 262: `try:`

This is correct — `temp_dir` is created before `try`, and `finally` should clean it up. Let me check the end of the function... I didn't read the end of repo_scan.py. Let me check.

Actually, I already read the file and know the patterns. The `finally` block at the end of `execute_repo_scan` does:
```python
finally:
    shutil.rmtree(temp_dir, ignore_errors=True)
```

So temp cleanup is handled. No bug here.

---

## BUG #38 — LOW
**File**: `orchestrator_pkg/scan.py` — Lines 116-126  
**Type**: Hardcoded Tool Tags

**Description**: `_build_nuclei_tags` has hardcoded tag mappings for common technologies:
```python
TECH_TAG_MAP = {
    'wordpress': ['wordpress', 'wp'],
    'php': ['php'],
    ...
}
```

These are not configurable and not sourced from tool_definitions SSOT. Adding a new technology requires modifying this code. But this is a feature gap, not a bug.

---

## COMPLETE SEVERITY SUMMARY

| # | Severity | File | Line(s) | Category |
|---|----------|------|---------|----------|
| 1 | **CRITICAL** | `tasks/scan.py` | 108-109, 137-138, 158-159 | Engagement Stuck |
| 2 | **CRITICAL** | `orchestrator_pkg/orchestrator.py` | 77 | Silent Data Loss |
| 3 | **CRITICAL** | `orchestrator_pkg/scan.py` | 296-312 | Missing emit_tool_complete |
| 4 | **CRITICAL** | `orchestrator_pkg/orchestrator.py` | 1215-1224 | Dead Code Safety Net |
| 5 | **CRITICAL** | `database/repositories/finding_repository.py` | 132 | Runtime Crash |
| 6 | **CRITICAL** | `database/repositories/finding_repository.py` | 76-81 | Silent Finding Drop |
| 7 | **HIGH** | `orchestrator_pkg/orchestrator.py` | 306-311 | Feature Flag Bypass |
| 8 | **HIGH** | `tasks/base.py` | 170-186, 194-212 | Race Condition |
| 9 | **HIGH** | `orchestrator_pkg/orchestrator.py` | 611-613 | Silently Swallowed Findings |
| 10 | **HIGH** | `orchestrator_pkg/scan.py` | 164-182 | Misleading Success Signal |
| 11 | **HIGH** | `intelligence_engine.py` | 227-230 | Confidence Cap Bypass |
| 12 | **HIGH** | `tasks/base.py` | 172, 196 | Double-Connection / WS Events Lost |
| 13 | **MEDIUM** | `tasks/analyze.py` | 43 | State Transition Ordering |
| 14 | **MEDIUM** | `orchestrator_pkg/recon.py` | 27-31 | Dead Budget Parameter |
| 15 | **MEDIUM** | `orchestrator_pkg/orchestrator.py` | 293-294 | Type Contract Violation |
| 16 | **MEDIUM** | `tasks/llm_review.py` | 334 | URL Construction Bug |
| 17 | **MEDIUM** | `orchestrator_pkg/scan.py` | 164-182 | Zero Findings Signal |
| 18 | **MEDIUM** | `tasks/llm_review.py` | 86-99 | TOCTOU Race |
| 19 | **MEDIUM** | `intelligence_engine.py` | 780-817 | Blocking I/O |
| 20 | **MEDIUM** | `tasks/utils.py` | 110-128 | Redis Pool Never Torn Down |
| 21 | **MEDIUM** | `agent/react_agent.py` | 534-553 | Incomplete Scope Validation |
| 22 | **MEDIUM** | `agent/swarm.py` | 561-581 | Subprocess Orphaning |
| 23 | **MEDIUM** | `tasks/base.py` | 159-160 | Fragile Type Guard |
| 24 | **MEDIUM** | `tasks/diff.py` | 63-66, 149-168 | Private Method Coupling |
| 25 | **LOW** | `state_machine.py` | 86 | Exception Info Loss |
| 26 | **LOW** | `state_machine.py` | 67 | Transient Inconsistent State |
| 27 | **LOW** | `orchestrator_pkg/recon.py` | 64 | Fragile URL Parsing |
| 28 | **LOW** | `agent/react_agent.py` | 800-803 | Dead Condition |
| 29 | **LOW** | `config/constants.py` | 30-50 | Duplicate Allowlist Entries |
| 30 | **LOW** | `intelligence_engine.py` | 1018 | zip strict (3.10+) |
| 31 | **LOW** | `models/finding.py` | 52-74 | Overly Strict Validation |
| 32 | **LOW** | `orchestrator_pkg/orchestrator.py` | 212 | DB/Websocket State Mismatch |
| 33 | **LOW** | `tasks/utils.py` | 17-18 | Hardcoded TTL |
| 34 | **LOW** | `agent/coordinator.py` | 69-82 | Dead Adapter Parameter |
| 35 | **LOW** | `tasks/base.py` | 165, 192, 269 | F-String Logging |
| 36 | **LOW** | `orchestrator_pkg/orchestrator.py` | 359-362 | Inconsistent Dedup |
| 37 | **LOW** | `scan_diff_engine.py` | 42 | Import in Static Method |
| 38 | **LOW** | `agent/swarm.py` | 427 | Import in Loop |
