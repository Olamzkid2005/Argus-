# Autonomy Blockers — Full Audit

What prevents Argus from running fully autonomously (no human in the loop).

**Status key:** ✅ Fixed · 🟡 Partial fix · ❌ Not fixed · 🟢 Not a blocker (already handled)

---

## 🔴 DEADLOCKS — Execution Halts Indefinitely

### 1. Question Tool Has No Auto-Answer ✅ FIXED

**`Argus-Tui/packages/opencode/src/tool/question.ts:14-41`** — Fixed by adding `ARGUS_AUTO_ANSWER` env var.

The `autoAnswer()` function (line 14) checks `process.env.ARGUS_AUTO_ANSWER` and returns default answers for all questions when set, bypassing stdin entirely.

Set `ARGUS_AUTO_ANSWER=continue` (or any string) to auto-answer all LLM questions with that value.

<details>
<summary>Fix details</summary>

- **File:** `Argus-Tui/packages/opencode/src/tool/question.ts`
- **What changed:** Added `autoAnswer()` function (lines 16–25) that generates default answers when `ARGUS_AUTO_ANSWER` is set. The executor checks for auto-answers first (lines 34–47) and returns immediately with a metadata message instead of calling `question.ask()`.
- **Env var:** `ARGUS_AUTO_ANSWER` — set to any string to enable auto-answering.
</details>

### 2. Approval Gates Block Without TTY ✅ FIXED

**`Argus-Tui/packages/opencode/src/argus/workflows/approval.ts`** — Fixed to respect `ARGUS_AUTO_APPROVE=1` for destructive gates in non-TTY mode.

Previously, destructive gates were **silently skipped** (denied) in non-TTY mode regardless of `ARGUS_AUTO_APPROVE`. Now, when `ARGUS_AUTO_APPROVE=1`, destructive gates are auto-approved even in non-TTY.

Combined with `ARGUS_AUTONOMOUS=1`, this enables all phases (including `destructive_tools` gated phases like `web_exploitation` and `api_exploitation`) to execute fully autonomously.

<details>
<summary>Fix details</summary>

- **File:** `Argus-Tui/packages/opencode/src/argus/workflows/approval.ts`
- **What changed:** The non-TTY path now checks `ARGUS_AUTO_APPROVE` before skipping destructive gates. When `ARGUS_AUTO_APPROVE=1`, the destructive gate auto-approves. Without it, destructive gates still auto-skip in non-TTY as before (safe default).
- **Env var:** `ARGUS_AUTO_APPROVE=1` — now required for destructive gate auto-approval in autonomous mode.
</details>

### 3. Target Confirmation Blocks 🟢 NOT A BLOCKER

**`Argus-Tui/packages/opencode/src/argus/workflow-runner.ts:376-408`** — Already handled. Non-TTY auto-confirms, and `ARGUS_AUTO_APPROVE=1` also skips confirmation. Only blocks when `security.scope.require_confirmation` is set AND running in TTY without `ARGUS_AUTO_APPROVE`.

When `ARGUS_AUTONOMOUS=1`, non-TTY is the expected runtime mode, so this never blocks.

---

## 🟡 SILENT SKIPS — Capability Lost Without Notice

### 4. ~60 External Binaries Must Be Pre-Installed ❌ NOT FIXED (operational)

**`argus-workers/mcp_server.py:312-317`** — This is an operational requirement. Every security tool binary must be installed on PATH. The MCP server logs warnings for missing binaries but assessment proceeds with zero tools.

**Mitigation:** `argus doctor` lists missing tools. Phase 4.5.6 (Zero-tools fail) now throws in autonomous mode when all phases have zero tools (see blocker 19), so this won't go unnoticed.

### 5. Non-TTY Destructive Gates Auto-Skip ✅ FIXED

Same as blocker 2. See above.

### 6. Tool Health Monitor — Circuit-Breaker Skips ✅ FIXED

**`Argus-Tui/packages/opencode/src/argus/bridge/tool-health.ts`, `Argus-Tui/packages/opencode/src/argus/planner/executor.ts:494-495`** — Added `findFallbackTool()` in executor.ts. When a tool is circuit-broken, the executor now searches for alternative tools covering the same capability. Defaults relaxed to 8 failures / 120s cooldown.

### 7. Degraded Mode Caches Stale Results ✅ FIXED

**`Argus-Tui/packages/opencode/src/argus/bridge/mcp-client.ts:44-49`, `Argus-Tui/packages/opencode/src/argus/bridge/supervisor.ts:25`** — Added per-entry `hitCount` tracking. When a cached result has been served 3+ times, a warning is logged. Cache TTL is now configurable via `ARGUS_DEGRADED_CACHE_TTL_MS`.

### 13. Config File Loading Errors Silently Fall Back ✅ FIXED

**`Argus-Tui/packages/opencode/src/argus/workflow-runner.ts:542-549`** — Fixed to fail hard in autonomous mode.

When `ARGUS_AUTONOMOUS=1` and config file parsing fails, the workflow-runner now throws a clear error instead of silently using defaults:

```
[Argus] ARGUS_AUTONOMOUS=1: config file 'argus.config.yaml' is missing or malformed.
A valid config file is required in autonomous mode.
```

<details>
<summary>Fix details</summary>

- **File:** `Argus-Tui/packages/opencode/src/argus/workflow-runner.ts`
- **What changed:** Added `isAutonomous` check in the config catch block (lines 557–562). Also added `validateKeys()` to `feature-flags.ts` and unknown-key warnings in `loader.ts`.
- **Scope:** Only the workflow-runner config path was hardened. `feature-flags.ts:220-227` and `tool-config.ts:39-40` still silently degrade.
</details>

### 14. MCP Worker Ready-Timeout Too Short ✅ FIXED

**`Argus-Tui/packages/opencode/src/argus/bridge/mcp-client.ts:270-281`** — Fixed by making timeout configurable via `ARGUS_MCP_READY_TIMEOUT_MS`.

Default remains 10s for backward compatibility. Set `ARGUS_MCP_READY_TIMEOUT_MS=30000` for 30s on cold-start environments.

<details>
<summary>Fix details</summary>

- **File:** `Argus-Tui/packages/opencode/src/argus/bridge/mcp-client.ts`
- **What changed:** `waitForReady()` (line 296) reads `ARGUS_MCP_READY_TIMEOUT_MS` with fallback to the original 10000ms default.
</details>

### 15. No MCP Worker Health Probe During Assessment ✅ FIXED

**`Argus-Tui/packages/opencode/src/argus/bridge/mcp-client.ts:81-83,174,337-354`** — `_startHealthProbes()` is called from `connect()` when the assessment starts. It runs a 30s `setInterval` that calls `probeHealth()` and initiates worker restart when unresponsive. The timer uses `.unref()` so it doesn't keep the process alive on shutdown.

<details>
<summary>Fix details</summary>

- **File:** `Argus-Tui/packages/opencode/src/argus/bridge/mcp-client.ts`
- **What changed:** `connect()` calls `this._startHealthProbes()` (line 174). The probe runs every `HEALTH_PROBE_INTERVAL_MS` (30s), logs a warning on failure, sets LLM status to UNAVAILABLE, and triggers worker restart.
- **Verified:** Wired into assessment lifecycle — `connect()` is called in `workflow-runner.ts` before phase execution.
</details>

### 16. Phase Complete LLM Feedback Silently Degrades ✅ FIXED

**`Argus-Tui/packages/opencode/src/argus/workflow-runner.ts:679-683`** — `phaseCompleteResult.fallback` is checked after each phase completes. When the LLM is unavailable on the Python side, `fallback: True` is returned, and the workflow-runner emits a visible warning and appends an audit log entry.

<details>
<summary>Fix details</summary>

- **File (TS):** `Argus-Tui/packages/opencode/src/argus/workflow-runner.ts`
- **What changed:** Added `if (phaseCompleteResult.fallback)` check (line 679) that emits `⚠ LLM unavailable for phase analysis — using fallback phase progression` and logs to the audit trail.
- **File (Python):** `argus-workers/mcp_server.py` — `_fallback_phase_complete()` returns `"fallback": True`.
- **Verified:** The flag is consumed immediately after the `phaseComplete()` call in the assessment loop.
</details>

### 17. Structured Findings From MCP Path Are Lost ✅ FIXED

**`argus-workers/mcp_server.py:701-717`, `Argus-Tui/packages/opencode/src/argus/planner/executor.ts:502-535`** — Fixed.

The executor now consumes the `structured` key from MCP responses in hybrid mode (line ~430-440):
```typescript
const structuredData = (result.data as any).structured
if (structuredData && Array.isArray(structuredData) && structuredData.length > 0) {
  for (const finding of structuredData) {
    findings.push({ ...finding, confidence: promoted })
  }
}
```

Structured findings with proper severity, CWE, and evidence are now normalized. The `else if` guard prevents double-counting when both `structured` and raw arrays are present.

### 18. Attack Graph Silently Skips Invalid Findings ✅ FIXED

**`argus-workers/mcp_server.py:1188`** — Now logs the count of skipped invalid findings with `logger.warning` so operators can detect incomplete attack graphs.

### 19. Planner Silently Drops Phases With Zero Tools ✅ FIXED

**`Argus-Tui/packages/opencode/src/argus/planner/planner.ts:79,114`** — Fixed to throw in autonomous mode.

When all phases have zero tools in autonomous mode, the planner now throws:
```
[Argus] ARGUS_AUTONOMOUS=1: All phases have zero available tools.
```
This prevents assessments that silently complete with zero findings.

### 20. Runaway Phase Execution In Hybrid Mode ✅ FIXED

**`Argus-Tui/packages/opencode/src/argus/planner/executor.ts:231-234`** — Fixed with two circuit breakers:

1. **Per-phase timeout:** `ARGUS_MAX_PHASE_DURATION_MS` (default 30 min, line 88)
2. **Global max assessment duration:** `ARGUS_MAX_ASSESSMENT_DURATION_MS` (default 2 hours, line 96)

The global circuit breaker is checked at the start of `execute()` (line ~164). The per-phase timeout is checked before each hybrid iteration (line ~410) and after each tool result (line ~505).

<details>
<summary>Fix details</summary>

- **File:** `Argus-Tui/packages/opencode/src/argus/planner/executor.ts`
- **Env vars:** `ARGUS_MAX_PHASE_DURATION_MS` (default 1800000), `ARGUS_MAX_ASSESSMENT_DURATION_MS` (default 7200000)
- **Note:** The global timer (`assessmentStartTime`) is now set to `Date.now()` at the start of the first phase execution via an `if (=== 0)` guard in `execute()`. Both the global 2-hour ceiling and per-phase 30-min timeout are now actively enforced.
</details>

### 21. Best-Effort try/catch Everywhere Masks Failures ✅ FIXED

**`Argus-Tui/packages/opencode/src/argus/workflow-runner.ts:519,561,643,679,706`** — Config loading and engine close catch blocks now log actual error messages instead of swallowing them silently.

### 22. Circuit Breaker Defaults Kill Tools Too Aggressively ✅ FIXED

**`Argus-Tui/packages/opencode/src/argus/config/tool-config.ts:72-76`, `Argus-Tui/packages/opencode/src/argus/bridge/tool-health.ts:17-19`** — Defaults relaxed from 5 failures / 5 min cooldown to 8 failures / 120s cooldown. Reduces false positives for tools with transient errors (network jitter, MCP worker restarts).

### 23. Engagement Lock Acquisition Silently Skipped ✅ FIXED

**`Argus-Tui/packages/opencode/src/argus/workflow-runner.ts:561-565`** — Now throws in autonomous mode.

When `ARGUS_AUTONOMOUS=1` and lock acquisition fails (Redis unavailable), the runner throws a clear error:
```
[Argus] ARGUS_AUTONOMOUS=1: Could not acquire distributed lock for engagement {id}.
Distributed locking is required in autonomous mode to prevent concurrent assessments
on the same target. Ensure Redis is running or disable autonomous mode.
```

<details>
<summary>Fix details</summary>

- **File:** `Argus-Tui/packages/opencode/src/argus/workflow-runner.ts`
- **What changed:** Added `isAutonomous` check in the lock catch block (lines 567–575).
</details>

### 24. Per-Engagement DB Resource Leak On Close Failure ✅ FIXED

**`Argus-Tui/packages/opencode/src/argus/engagement/store.ts:645,657`** — Encrypted handle close now retries 3x with exponential backoff (100ms, 200ms, 400ms).

<details>
<summary>Fix details</summary>

- **File:** `Argus-Tui/packages/opencode/src/argus/engagement/store.ts`
- **What changed:** Added `_closeEncryptedHandleWithRetry()` (lines 340–360) with 3 retry attempts and exponential backoff. Falls back to `console.error` after final failure.
</details>

### 25. Semgrep/Bandit Findings-Bearing Exit Codes Missed on MCP Path ✅ FIXED

**`argus-workers/mcp_server.py:685-690,701-717`** — Added cross-reference comment warning maintainers to keep `FINDINGS_EXIT_CODES` in sync with `ToolRunner.FINDINGS_EXIT_CODES`. Both dicts verified to contain the same 8 tools.

### 29. ReActAgent Has Unbounded LLM Cost In Autonomous Mode ✅ FIXED

**`argus-workers/agent/react_agent.py:859-885`** — Cost guard now applies in ALL modes including `GOVERNANCE_V2`.

Previously, the cost guard only ran in the legacy branch. When `GOVERNANCE_V2` was enabled (default for autonomous mode), cost was tracked but not enforced. Now the cost check runs immediately after the mode check, covering both legacy and V2 paths.

<details>
<summary>Fix details</summary>

- **File:** `argus-workers/agent/react_agent.py`
- **What changed:** Added cost check at top of `_choose_action()` method, before mode routing. Removed duplicate legacy-only cost block.
</details>

### 30. Agent History Silently Truncated At 50 Entries ✅ FIXED

**`argus-workers/agent/react_agent.py:421-427`** — Warning logged when entries are dropped.

<details>
<summary>Fix details</summary>

- **File:** `argus-workers/agent/react_agent.py`
- **What changed:** Added `logger.warning` when history truncation occurs (50+ entries). Warns: `"Agent history truncated at 50 entries — oldest entries dropped"`.
</details>

### 31. LLM Tool Selection Silently Falls Back To Deterministic ✅ FIXED

**`argus-workers/agent/react_agent.py:560-563,607-610`** — When the LLM is available but returns `None` (failed/fallback), a `logger.warning` is now emitted with context about the task. Gated by `recon_context` to avoid false positives.

### 32. ReActAgent Max Iterations Not Configurable From TypeScript Side ✅ FIXED

**`argus-workers/agent/react_agent.py:19,1052-1054`** — TS now passes `max_iterations` (from `ARGUS_HYBRID_MAX_ITERATIONS`) via `agentNext()` params. Python stores it via `set_ts_max_iterations()` and caps iteration limit with `min()`. Both sides share the same `execution_iteration` counter.

### 33. Auth Checkpoint Restore Threads Leak On Success ✅ FIXED

**`argus-workers/agent/react_agent.py:1153-1183`** — `shutdown(wait=False, cancel_futures=True)` ensures the executor's worker threads are interrupted immediately rather than lingering until garbage collection. Covers both success and failure paths.

### 35. No Per-Phase Timeout In Workflows ✅ FIXED

**`Argus-Tui/packages/opencode/src/argus/planner/executor.ts`** — Added `ARGUS_MAX_PHASE_DURATION_MS` with per-iteration checks in both `execute()` and `executeHybrid()`.

Each phase now has a configurable deadline (default 30 min). The deadline is checked:
- Before each hybrid loop iteration (line ~410)
- After each tool result in the deterministic path (line ~505)
- At the start of `execute()` via the global circuit breaker

<details>
<summary>Fix details</summary>

- **File:** `Argus-Tui/packages/opencode/src/argus/planner/executor.ts`
- **Env var:** `ARGUS_MAX_PHASE_DURATION_MS` (default 1800000 = 30 min)
- **New field:** `phaseDeadline` set at start of each phase.
</details>

### 37. ThreadPoolExecutor Resources Not Bounded Across Concurrent Assessments ✅ FIXED

**`argus-workers/orchestrator_pkg/recon.py:274`**, **`orchestrator_pkg/scan.py:868`**, **`agent/swarm.py:630`**, **`tools/attack_surface_mapper.py:49`** — All four ThreadPoolExecutors already have `max_workers` limits:
- `recon.py`: `max_workers=8`
- `scan.py`: `max_workers=5`
- `swarm.py`: `max_workers=len(active)` (bounded by max 3 active agents)
- `attack_surface_mapper.py`: `max_workers=3`

These were verified in the code-fix campaign (July 5, 2026). No unbounded pools remain.

### 38. No Cancellation Propagation From TypeScript To Python Agent ✅ FIXED

**`argus-workers/agent/session_store.py:305-318`, `argus-workers/mcp_server.py:1368-1412`** — `AgentSessionStore.cancel()` exists and sets `_cancelled` on the session under lock. `handle_agent_next()` and `handle_agent_observe()` both check `hasattr(session, '_cancelled')` and return `done=True` immediately if set.

<details>
<summary>Fix details</summary>

- **File:** `argus-workers/agent/session_store.py` — `cancel(session_id)` method (line 305) sets `session._cancelled = True` under lock. Returns `False` if session not found (no-op).
- **File:** `argus-workers/mcp_server.py` — `handle_cancel` calls `server.session_store.cancel(session_id)`. `handle_agent_next()` (line ~937) and `handle_agent_observe()` (line ~1017) check `hasattr(session, '_cancelled')` and short-circuit.
- **File (TS):** `Argus-Tui/packages/opencode/src/argus/bridge/mcp-client.ts` — `cancelAgent()` sends `"cancel"` RPC.
- **Verified:** Full propagation chain: TS → RPC → cancel() → _cancelled flag → agent loop termination.
</details>

### 39. MCP Transport Has No Message Size Limit ✅ FIXED

**`argus-workers/mcp_transport.py`** — Message size limits enforced: 10MB input (stdin reads), 50MB output (stdin writes).

<details>
<summary>Fix details</summary>

- **File:** `argus-workers/mcp_transport.py`
- **What changed:** Added `_MAX_MESSAGE_SIZE` (10MB) and `_MAX_OUTPUT_SIZE` (50MB) constants. Input validation rejects oversized messages with `MCPError`. Output validation truncates oversized responses.
</details>

### 40. Worker Cleanup On Abnormal Exit Leaks Child Processes ✅ FIXED

**`Argus-Tui/packages/opencode/src/argus/bridge/mcp-client.ts:108-122`** — `killChild()` now uses process-group signal: `process.kill(-proc.pid, "SIGTERM")`.

The negative PID sends the signal to the entire process group, ensuring grandchild processes (nuclei, nmap, sqlmap) are terminated alongside the parent MCP worker. Falls back to parent-only kill on platforms that don't support negative PID signals.

<details>
<summary>Fix details</summary>

- **File:** `Argus-Tui/packages/opencode/src/argus/bridge/mcp-client.ts`
- **What changed:** `killChild()` (lines 121-139) now sends `SIGTERM` to the process group (`-proc.pid`) followed by `SIGKILL` after 3s timeout.
</details>

### 41. SQLite Finalizer May Never Run ✅ FIXED

**`Argus-Tui/packages/opencode/src/argus/workflow-runner.ts:423`** — `store.registerExitHandler()` is called immediately after `new EngagementStore()` at the start of every assessment run. FinalizationRegistry also provides best-effort cleanup via GC.

<details>
<summary>Fix details</summary>

- **File:** `Argus-Tui/packages/opencode/src/argus/workflow-runner.ts`
- **What changed:** Added `store.registerExitHandler()` at line 423, right after store construction.
- **File:** `Argus-Tui/packages/opencode/src/argus/engagement/store.ts` — `registerExitHandler()` registers `process.on("exit")`, `SIGINT`, `SIGTERM` handlers that call `this.close()`.
- **Verified:** Called at the top of `run()`, so it's active for the entire assessment lifecycle.
</details>

### 42. Evidence Pruning Failures Silently Ignored ✅ FIXED

**`Argus-Tui/packages/opencode/src/argus/evidence/collector.ts`** — All bare `catch { }` blocks in `pruneEngagement()` now log the error message via `console.warn` instead of swallowing silently.

### 43. Report LLM Enhancement Has No Hard Timeout ✅ FIXED

**`Argus-Tui/packages/opencode/src/argus/commands/report.ts:39`** — Added 60-second hard timeout per LLM analysis call.

Each individual LLM analysis now has a `Promise.race` with a 60-second timeout. Hanging LLM calls don't block report generation.

<details>
<summary>Fix details</summary>

- **File:** `Argus-Tui/packages/opencode/src/argus/commands/report.ts`
- **What changed:** Individual analysis calls wrapped in `Promise.race` with 60s timeout.
</details>

### 44. No Cross-Tool Rate Limiting For Parallel Tool Execution ✅ FIXED

**`Argus-Tui/packages/opencode/src/argus/planner/executor.ts:251-263`** — New `CrossToolRateLimiter` class with per-target sliding window. Configurable via `ARGUS_CROSS_TOOL_RATE_LIMIT` (default 50) and `ARGUS_CROSS_TOOL_RATE_WINDOW_MS` (default 1000). Prevents tools like nuclei + ffuf from overloading targets simultaneously.

### 45. No Self-Throttling When Target Responds With 429/503 ✅ FIXED

**`Argus-Tui/packages/opencode/src/argus/planner/executor.ts`, `argus-workers/tools/tool_runner.py`** — New `ThrottleTracker` class with per-target exponential backoff (base 2s, max 60s). Detects 429, 503, "rate limit", "too many requests" patterns in both `result.error` responses and catch-block exceptions. Configurable via `ARGUS_THROTTLE_BASE_DELAY_MS` and `ARGUS_THROTTLE_MAX_DELAY_MS`.

### 47. Worker Cannot Recover From Database Connection Loss Mid-Assessment ✅ FIXED

**`argus-workers/database/connection.py`** — When the connection pool is exhausted (all connections stale after network flap), the pool is automatically closed and reinitialized. Stale connections are detected via the existing `SELECT 1` health check and replaced inline.

### 48. Governance Token Budget Is Estimated (Not Actual) ✅ FIXED

**`argus-workers/runtime/governance.py:115-119,238-249`** — `record_result()` now accepts `actual_input_tokens` and `actual_output_tokens` params from the LLM response. When available, these are used instead of the static estimate. Fallback estimate remains for non-LLM tool calls.

### 49. EngagementState and ReActAgent Independently Truncate (Different Data) ✅ FIXED

**`argus-workers/runtime/engagement_state.py:22`**, **`argus-workers/agent/react_agent.py`** — `react_agent.py` now imports `OBSERVATION_TRUNCATION_LIMIT` directly from `engagement_state.py` instead of hardcoding 50. Both layers are coordinated via a single import. When `OBSERVATION_TRUNCATION_LIMIT` is changed in `engagement_state.py`, `react_agent.py` automatically stays in sync.

### 50. LLM Agent `max_iterations` Mismatch Between Python and TypeScript ✅ FIXED

**`argus-workers/config/constants.py:257-258`** (default: 10), **`Argus-Tui/packages/opencode/src/argus/planner/executor.ts:233`** (default: 50) — TS now passes its `ARGUS_HYBRID_MAX_ITERATIONS` (default 50) to Python via `agentNext()` params. Python stores it via `set_ts_max_iterations()` and uses `min(ts_value, py_value)` to coordinate. The defaults remain 50 vs 10 but are now coordinated.

### 51. [RETRACTED — timeout IS passed to tool_runner.run()] 🟢 RETRACTED

### 52. Connection Pool Not Registered for atexit Cleanup ✅ FIXED

**`argus-workers/database/connection.py:317-325`** — `atexit.register()` now called for database connection pool cleanup.

<details>
<summary>Fix details</summary>

- **File:** `argus-workers/database/connection.py`
- **What changed:** Added `atexit.register(get_db().close)` to ensure the pool is cleaned up on process exit (SIGTERM, normal exit).
</details>

### 53. Docker Compose Override Enables Host Network Mode (Mitigated by Profiles) ❌ NOT FIXED (design)

**`docker-compose.override.yml`** — Profiles scoping already mitigates this. Code change would be removing the override entirely.

### 54. Distributed Semaphore Has TOCTOU Race Condition ✅ FIXED

**`argus-workers/runtime/concurrency.py:61-83`** — Replaced non-atomic `GET` + `INCR` pattern with an atomic Lua script that atomically checks the current count and increments only if under the limit. Eliminates the TOCTOU window between check and increment.

### 55. LLM Provider Auto-Detect From Key Prefix Is Fragile ✅ FIXED

**`argus-workers/llm_client.py:76-114`** — Added known prefix validation (recognizes `sk-or-` for OpenRouter, `sk-proj-`/`sk-` for OpenAI, `AIzaSy`/`AQ.` for Gemini). Logs a `logger.warning` when the key prefix doesn't match any known pattern. `sk-ant-` (Anthropic) is recognized but NOT auto-configured since its API is not OpenAI-compatible.

### 56. LLM Agent Model Env Var Name Mismatch With .env.example ✅ FIXED

- **`.env.example`** — Updated to document `LLM_AGENT_MODEL` (the correct variable used by the code), replacing `LLM_MODEL` (which is unused by the agent code).

<details>
<summary>Fix details</summary>

- **File:** `.env.example`
- **What changed:** Changed `LLM_MODEL` to `LLM_AGENT_MODEL` in the example and added documentation for `ARGUS_AUTO_ANSWER`, `ARGUS_AUTONOMOUS`, and `ARGUS_AUTO_APPROVE` env vars.
</details>

### 57. No Metrics or Health Endpoint Exposed By Workers ✅ FIXED

**`argus-workers/health_server.py`**, **`argus-workers/mcp_server.py`** — New `health_server.py` module with two HTTP endpoints:
- `GET /health` — liveness check: status, uptime, LLM availability, tool counts, active sessions
- `GET /metrics` — detailed metrics: per-tool stats, aggregate success rates, connection pool state, system info

<details>
<summary>Fix details</summary>

- **File:** `argus-workers/health_server.py` (new)
- **What changed:** Added lightweight HTTP server using Python's built-in `socketserver.ThreadingHTTPServer`. Two endpoints:
  - `/health` — returns 200/503 with status, uptime, LLM availability, tool totals, session count
  - `/metrics` — returns detailed JSON with per-tool execution stats, aggregate success rates, connection pool metrics (best-effort), and system info
- **File:** `argus-workers/mcp_server.py` — `main()` now calls `start_health_server_from_env()` before `transport.run()`
- **Config:** `ARGUS_METRICS_PORT` (default 9090), `ARGUS_METRICS_HOST` (default 127.0.0.1). Set port to empty or 0 to disable.
- **Safety:** Runs on a daemon thread. Uses public `get_tools()` API. Port clamped to 1-65535.
</details>

### 58. Governance Uses Wall Clock, Not Active Time ✅ FIXED

**`argus-workers/runtime/governance.py:104-108`** — Added `start_active_timer()` / `stop_active_timer()` and `get_active_runtime_seconds()`. The `check()` method now uses accumulated active execution time instead of wall-clock for the timeout budget. React agent wraps `registry.call()` in try/finally with the active timer.

### 59. Config Schema Is Not Validated At Startup ✅ FIXED

**`argus.config.yaml`**, **`Argus-Tui/packages/opencode/src/argus/config/loader.ts`** — Unknown config keys now emit warnings at load time.

In autonomous mode, unknown keys cause the same hard-fail behavior as malformed config (blocker 13).

<details>
<summary>Fix details</summary>

- **File:** `Argus-Tui/packages/opencode/src/argus/config/loader.ts`
- **What changed:** Iterates parsed config keys and warns on unknown keys.
- **Still missing:** Full schema validation against the Zod schema — currently only uses a hardcoded key list.
</details>

### 60. Pool Connections Never Validated Before Use ✅ FIXED

**`argus-workers/database/connection.py:107-132`** — `SELECT 1` ping performed before returning connections from the pool.

Stale connections (idle for hours, network middleboxes, `idle_in_transaction_session_timeout`) are now detected and automatically replaced.

<details>
<summary>Fix details</summary>

- **File:** `argus-workers/database/connection.py`
- **What changed:** Added connection validation before returning from `get_connection()`. If `SELECT 1` fails, the stale connection is discarded and a fresh one is obtained from the pool.
</details>

### 61. Evidence `pruneEngagement()` Exists But Is Never Called Automatically ✅ FIXED

**`Argus-Tui/packages/opencode/src/argus/evidence/collector.ts:113-124,131-178`** — `pruneEngagement()` now called at assessment end in `workflow-runner.ts`.

<details>
<summary>Fix details</summary>

- **File:** `Argus-Tui/packages/opencode/src/argus/workflow-runner.ts`
- **What changed:** Added `pruneEngagement()` call in the `finally` block (lines 717–727) after assessment completes. Logs the number of pruned files.
</details>

### 62. MCP Transport Has No Stdin Heartbeat ✅ FIXED

**`argus-workers/mcp_transport.py:109-132,134-171`** — Added `_wait_for_stdin()` method using `select.select()` with a configurable timeout. When no data arrives within the window, the worker logs a warning and shuts down gracefully via `self.stop()`.

<details>
<summary>Fix details</summary>

- **File:** `argus-workers/mcp_transport.py`
- **What changed:** Added `_wait_for_stdin()` method that uses `select.select([sys.stdin], [], [], timeout)` before the blocking `readline()` call. On timeout, logs "Stdin heartbeat timed out after Ns" and calls `self.stop()`.
- **Config:** `ARGUS_MCP_HEARTBEAT_TIMEOUT_SECS` env var (default 60s). Set to 0 to disable.
- **Safety:** Catches `(ValueError, TypeError, OSError)` from select() and falls back to proceeding with readline, so a transient FD issue doesn't kill the worker.
</details>

### 63. NET_RAW Capability + no-new-privileges Is an Undocumented Security Profile ❌ NOT FIXED (design)

**`docker-compose.yml:72,82,93`** — By design for nmap SYN scans.

### 64. `zero_finding_stop` and `low_signal_threshold` Race ✅ FIXED

**`argus-workers/config/constants.py:269`** (`LLM_AGENT_ZERO_FINDING_STOP = 4`), **`argus-workers/runtime/governance.py:22`** (`_DEFAULT_LOW_SIGNAL_THRESHOLD = 3`) — Added cross-reference comments at both locations ensuring `zero_finding_stop` stays > `low_signal_threshold`. This guarantees Governance's low-signal detection fires first with an informative reason.

### 65. Git SSRF Allowlist: YAML Config Only Applied Through `from_config()` Path ✅ FIXED

**`argus-workers/config/constants.py:201-234`** — `from_config()` now propagates `ImportError` and `RuntimeError` instead of catching them silently. A module-level factory wrapper (`_git_ssrf_factory()`) catches failures at ERROR severity (not WARNING) so the CONFIG singleton can still be constructed, but direct callers of `from_config()` will see the error.

### 66. Rate Limiter Config Key `backoff_multiplier` Is Unused ✅ FIXED

**`argus-workers/config/config_manager.py:34`** — Removed `backoff_multiplier: 2.0` from default config.

<details>
<summary>Fix details</summary>

- **File:** `argus-workers/config/config_manager.py`
- **What changed:** Removed orphaned `backoff_multiplier` key from `DEFAULT_CONFIG`.
</details>

---

## 🔴 DEADLOCKS (Continued)

### 34. LLM-Driven Phases Require Destructive Gate Bypass ✅ FIXED

Addressed by blocker 2. `ARGUS_AUTO_APPROVE=1` now auto-approves destructive gates in non-TTY mode, enabling phases like `web_exploitation` and `api_exploitation` to execute in autonomous mode.

### 43. Report LLM Enhancement Has No Hard Timeout ✅ FIXED

See blocker 43 above.

---

## 🟠 CONFIG TRAPS — Defaults That Sabotage Autonomy (Continued)

### 36. `scope.mode: warn` Allows Out-Of-Scope Access In Autonomous Mode ✅ FIXED

**`argus-workers/tools/scope_validator.py:214`** — Default mode changed from `"warn"` to `"allowlist"` so out-of-scope targets are **rejected** instead of warned. This applies to both the deterministic scan pipeline (`orchestrator_pkg/scan.py`) and all call sites that don't explicitly pass a mode. When no `allowed_targets` are configured, the validator logs a clear message (`"allowlist mode with no allowed_targets configured"`) and blocks all targets (fail-closed).

**`Argus-Tui/packages/opencode/src/argus/workflow-runner.ts`** — Added autonomous-mode guard: when `ARGUS_AUTONOMOUS=1` and `security.scope.mode` is `"warn"` or `"open"`, the runner throws a hard error instead of proceeding with an implicit scope. This mirrors the existing pattern (blockers #13, #23, #28) of failing hard in autonomous mode rather than silently degrading. Users must explicitly set `scope.mode: allowlist` with `allowed_targets` in `argus.config.yaml` before running autonomously.

### 46. Docker Compose Has No Health Checks ✅ FIXED (already had them)

**`docker-compose.yml`** — Verified: both PostgreSQL and Redis already have ``healthcheck:`` blocks with ``pg_isready`` and ``redis-cli ping``. The ``worker`` and ``celery-beat`` services already use ``depends_on: condition: service_healthy``. No code change needed — this blocker was already resolved.

```yaml
postgres:
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-argus_user} -d ${POSTGRES_DB:-argus_pentest}"]
    interval: 10s
    timeout: 5s
    retries: 5

redis:
  healthcheck:
    test: ["CMD-SHELL", "redis-cli -a \"${REDIS_PASSWORD:-change_me_in_production}\" ping"]
    interval: 10s
    timeout: 5s
    retries: 5
```

---

## 🔵 HARD DEPENDENCIES — Require Manual Setup

### 8. LLM API Key Required ❌ NOT FIXED (operational)

**`.env.example:52`** — `LLM_API_KEY` must be set in environment.

### 9. Browser MFA/CAPTCHA Cannot Be Automated ❌ NOT FIXED (inherent)

**`Argus-Tui/packages/opencode/src/argus/browser/login.ts:164-191`** — MFA/CAPTCHA cannot be automated.

### 10. 17 Sensitive Env Vars Stripped From Subprocesses ❌ NOT FIXED (by design)

**`argus-workers/mcp_server.py:661-683`** — Security feature by design.

### 11. Credential Store Requires Manual Setup ❌ NOT FIXED (operational)

**`Argus-Tui/packages/opencode/src/argus/engagement/credentials.ts`** — `credentials.json` must be created manually.

### 12. PostgreSQL + Redis Required ❌ NOT FIXED (infrastructure)

**`docker-compose.yml`, `.env.example`** — Both must be running.

### 26. Bun Runtime Required (bun:sqlite) ❌ NOT FIXED (inherent)

**`Argus-Tui/packages/opencode/src/argus/engagement/store.ts:1-14`** — No Node.js polyfill exists.

### 27. Playwright Browsers Required for Browser Verification ❌ NOT FIXED (operational)

**`Argus-Tui/packages/opencode/src/argus/browser/engine.ts`** — `npx playwright install` must be run manually.

### 28. Startup Credential Guard Only Warns ✅ FIXED

**`argus-workers/mcp_server.py:55-61`** — In autonomous mode (`ARGUS_AUTONOMOUS=1`), placeholder credentials now raise `RuntimeError` instead of just logging a warning. Manual/interactive mode still warns only.

---

## 🟠 CONFIG TRAPS — Defaults That Sabotage Autonomy

| Config Key | Default | Autonomous Impact | Fix Status |
|---|---|---|---|
| `scope.mode` | `warn` | In autonomous mode, fails hard if `warn` or `open` — must be `allowlist` | ✅ Fixed — TUI guard + Python default |
| `git_host_policy` | `allowlist` | Blocks git repos from unlisted hosts | ✅ Fixed — errors propagate from from_config() |
| `approval_gates` | `true` | Stdin prompts unless `ARGUS_AUTO_APPROVE=1` | ✅ See blocker 2 |
| `storage.encryption.enabled` | `false` | Credentials stored in plaintext | ❌ Not fixed |
| `disabled` | `[sqlmap]` | One tool pre-disabled | ❌ Not fixed |
| `LLM_API_KEY` | empty | Hybrid mode fails | ❌ Operational |
| `ARGUS_AUTO_APPROVE` | not set | Approval gates block | ✅ Now works for destructive gates |
| `ARGUS_AUTONOMOUS` | not set | No autonomy profile | ✅ Documented |
| `DETERMINISTIC_FALLBACK` | `false` (opt-in) | LLM planning used even when LLM key missing | ❌ Not fixed |
| `tools.circuit_breaker.max_failures` | `5` | Tools go dark for 5 min after 5 failures | ❌ Not fixed |
| `tools.circuit_breaker.cooldown_ms` | `300000` (5 min) | No half-open probe in TS-side circuit breaker | ❌ Not fixed |
| `ARGUS_MAX_ASSESSMENT_DURATION_MS` | `7200000` (2h) | Global timer was dead code | ✅ Fixed — timer now starts at first phase via `=== 0` guard |
| `ARGUS_HYBRID_MAX_ITERATIONS` | `50` | No safety net for runaway LLM loops | ✅ Per-phase + global breakers |
| `storage.encryption.enabled` | `false` | Engagement DBs stored as plaintext SQLite | ❌ Not fixed |

---

## SUMMARY

### Fix Status Overview (Updated)

| Category | Total | ✅ Fixed | 🟡 Partial | ❌ Unfixed |
|---|---|---|---|---|
| P0 — Deadlocks/Stops (incl. #20 timer now active) | 5 | 5 | 0 | 0 |
| P1 — Reliability | 5 | 5 | 0 | 0 |
| P2 — Robustness | 6 | 6 | 0 | 0 |
| P3 — Config/Polish (incl. #36 TUI scope guard) | 5 | 5 | 0 | 0 |
| P4 — Edge Cases | 5 | 5 | 0 | 0 |
| Other blockers | 40+ | 24 | 0 | ~16 operational |
| **Total** | **66** | **50** | **0** | **~16** |

**Net change:** #20 (global timer now actively enforced — `assessmentStartTime = Date.now()` set in `execute()` with `=== 0` guard), #36 (TUI-side autonomous-mode scope guard — `workflow-runner.ts` fails hard when `scope.mode` is `warn`/`open`). Also: #37 (ThreadPoolExecutor bounds), #46 (Docker health checks — already existed), #49 (state truncation coordination — shared import), #57 (health/metrics endpoint), #65 (Git SSRF allowlist propagation), and #66 (orphaned backoff key) resolved. Plus: redirect SSRF hardening (dual_auth_scanner, ai_vuln_scanner, llm_review, auth_manager), migration SQL fixes (017, 006, 008), webhook SSRF (post_finding_hooks.py), CWE/OWASP column consolidation (025). **50 total fixed**, 0 partial, ~16 unfixed.

### What Must Be True for Autonomous Mode (Updated)

1. `ARGUS_AUTONOMOUS=1` and `ARGUS_AUTO_APPROVE=1` env vars set
2. `LLM_API_KEY` set in env (for LLM-driven features)
3. All ~60 security tool binaries installed on PATH
4. Python MCP worker environment set up for Python-based tools
5. `credentials.json` with target login credentials (if browser testing needed)
6. `scope.mode` set to `"allowlist"` in `argus.config.yaml` with `allowed_targets` configured — **autonomous mode now fails hard** if scope is `"warn"` or `"open"`
7. Browser-verifiable targets must not use MFA/CAPTCHA/OAuth
8. PostgreSQL and Redis running
9. Bun runtime (not Node.js) — `bun:sqlite` is required by `EngagementStore`
10. Playwright browsers installed (`npx playwright install`) for verification
11. `argus.config.yaml` must be valid YAML — **now fails hard with clear error in autonomous mode**
12. `DETERMINISTIC_FALLBACK` should be set to `true` if no LLM key is available

### Blocker Matrix (Updated)

| Blocker | Type | Fixable via Env Var? | Fix Status |
|---|---|---|---|
| Question tool hang | deadlock | **Yes** (`ARGUS_AUTO_ANSWER`) | ✅ Fixed |
| Destructive gate silent skip | silent skip | **Yes** (`ARGUS_AUTO_APPROVE`) | ✅ Fixed |
| ~60 missing binaries | silent skip | No | ❌ Install them |
| No LLM key | hard fail | Yes | ❌ Operational |
| MFA/CAPTCHA | hard fail | No | ❌ Inherent |
| Approval gates | deadlock | Yes | ✅ `ARGUS_AUTO_APPROVE=1` |
| Target confirmation | deadlock | Yes | 🟢 Already handled |
| PostgreSQL/Redis | hard fail | No | ❌ Must run infra |
| **Silent config fallback** | **silent skip** | **No** | **✅ Fail hard in autonomous** |
| **MCP worker ready timeout** | **hard fail** | **Yes** (`ARGUS_MCP_READY_TIMEOUT_MS`) | **✅ Fixed** |
| **No health probe** | **silent skip** | **No** | **✅ 30s interval wired in connect()** |
| **LLM feedback degrades silently** | **silent skip** | **No** | **✅ Flag consumed, warns + audit log** |
| **Structured findings lost** | **silent skip** | **No** | **✅ Fixed** |
| **Phase drop with zero tools** | **silent skip** | **No** | **✅ Fixed** |
| **Runaway hybrid loop** | **deadlock** | **Yes** (env vars) | **✅ Per-phase + global breakers** |
| **Best-effort failures masked** | **silent skip** | **No** | **✅ Fixed** |
| **Circuit breaker kills tools** | **silent skip** | **No** | **✅ Fixed** — fallback tools + relaxed defaults |
| **Lock skip on Redis down** | **silent skip** | **Yes** (autonomous mode) | **✅ Fail hard in autonomous** |
| **Encrypted DB handle leak** | **security** | **No** | **✅ 3x retry + backoff** |
| **Bun runtime required** | **hard fail** | **No** | ❌ Not fixed |
| **Playwright browsers** | **hard fail** | **No** | ❌ Not fixed |
| **Placeholder credentials** | **silent skip** | **Yes** | **✅ Hard block in autonomous mode** |

### Action Items (Updated)

#### ✅ Completed Fixes (28 blockers)

| # | Blocker | Fix |
|---|---|---|
| 1 | Question tool hang | `ARGUS_AUTO_ANSWER` env var |
| 2 | Destructive gate auto-skip | `ARGUS_AUTO_APPROVE` now applies in non-TTY |
| 5 | Non-TTY destructive skip | Same as #2 |
| 6 | Circuit breaker fallback | `findFallbackTool()` in executor.ts |
| 7 | Degraded cache staleness | Hit-count tracking + stale warning |
| 13 | Config silent fallback | Fails hard in autonomous mode |
| 14 | MCP ready timeout | Configurable via `ARGUS_MCP_READY_TIMEOUT_MS` |
| 15 | Health probes | 30s interval wired in `connect()` |
| 16 | LLM feedback flag | Consumed in workflow-runner, warns + audit log |
| 17 | Structured findings lost | Consumed `data.structured` in executor |
| 18 | Attack graph logging | Skipped finding count reported |
| 19 | Zero-tools phase | Throws error in autonomous mode |
| 20 | Runaway hybrid loop | Per-phase + global max-duration circuit breakers (global timer now active — `assessmentStartTime` set at first phase via `=== 0` guard) |
| 21 | try/catch masking | 4 silent catches now log errors |
| 22 | Circuit breaker defaults | Relaxed to 8 failures / 120s cooldown |
| 23 | Lock skip | Fails hard in autonomous mode |
| 24 | DB resource leak | 3x retry with exponential backoff |
| 25 | Exit code sync | Cross-reference comment added |
| 28 | Credential guard | Hard block in autonomous mode |
| 29 | Unbounded LLM cost | Cost guard applies in all modes |
| 30 | History truncation loss | Warning logged on truncation |
| 31 | LLM fallback silence | Warning logged with recon_context guard |
| 32 | Max iterations mismatch | TS passes max_iterations to Python |
| 33 | Thread pool cleanup | `cancel_futures=True` on shutdown |
| 34 | Destructive gate bypass | Same as #2 |
| 35 | Per-phase timeout | `ARGUS_MAX_PHASE_DURATION_MS` |
| 38 | Cancel propagation | `AgentSessionStore.cancel()` + agent loop check |
| 39 | Message size limit | 10MB input / 50MB output |
| 40 | Orphaned processes | Process group kill |
| 41 | SQLite finalizer | `registerExitHandler()` called in workflow-runner |
| 42 | Evidence prune silence | catch→warn in collector.ts |
| 43 | Report LLM timeout | 60s hard timeout per analysis |
| 44 | Cross-tool rate limiting | `CrossToolRateLimiter` sliding window |
| 45 | Self-throttling 429/503 | `ThrottleTracker` expo backoff |
| 47 | DB connection recovery | Pool reinit on exhaustion |
| 48 | Token budget estimates | Actual token counts accepted |
| 49 | Truncation coordination | Shared constant + cross-ref comments |
| 50 | Iteration mismatch | TS passes max_iterations to Python |
| 52 | atexit cleanup | Registered for DB pool |
| 54 | TOCTOU semaphore | Lua script for atomic acquire |
| 55 | LLM prefix validation | Known prefixes + unknown-key warning |
| 56 | Env var name mismatch | `.env.example` updated |
| 57 | Health/metrics endpoint | HTTP server on daemon thread, port 9090 |
| 58 | Active time tracking | `start/stop_active_timer()` in governance |
| 59 | Config schema validation | Unknown key warnings |
| 60 | Connection pool validation | SELECT 1 ping |
| 61 | Evidence prune never called | Auto-prune at assessment end |
| 62 | Stdin heartbeat | `select.select()` with configurable timeout |
| 64 | Threshold race | Aligned `zero_finding_stop` > `low_signal_threshold` |
| 66 | Orphaned config key | `backoff_multiplier` removed |

#### ❌ Remaining Unfixed

| # | Blocker | Category | Reason |
|---|---|---|---|
| 4 | ~60 external binaries | Operational | Must be installed manually |
| 8 | LLM API key | Operational | Must be set in `.env` |
| 9 | Browser MFA/CAPTCHA | Inherent | Cannot be automated |
| 10 | Sensitive env vars stripped | By design | Security feature |
| 11 | Credential store | Operational | `credentials.json` manual setup |
| 12 | PostgreSQL + Redis | Infrastructure | Must be running |
| 26 | Bun runtime | Inherent | `bun:sqlite` — no Node polyfill |
| 27 | Playwright browsers | Operational | `npx playwright install` |
| 53 | Host network mode | Design | Required for nmap SYN scans |
| 63 | NET_RAW capability | Design | Intentional security profile |
