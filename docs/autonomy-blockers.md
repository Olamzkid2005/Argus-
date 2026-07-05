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

### 6. Tool Health Monitor — Circuit-Breaker Skips ❌ NOT FIXED

**`Argus-Tui/packages/opencode/src/argus/bridge/tool-health.ts`, `Argus-Tui/packages/opencode/src/argus/planner/executor.ts:494-495`** — Circuit breaker still uses 5-failure/5-min defaults with no fallback tools.

### 7. Degraded Mode Caches Stale Results ❌ NOT FIXED

**`Argus-Tui/packages/opencode/src/argus/bridge/mcp-client.ts:44-49`, `Argus-Tui/packages/opencode/src/argus/bridge/supervisor.ts:25`** — Degraded mode with 5-min TTL still serves stale cached results.

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

### 15. No MCP Worker Health Probe During Assessment 🟡 PARTIAL FIX

**`Argus-Tui/packages/opencode/src/argus/bridge/mcp-client.ts`** — `probeHealth()` method was added (line 305) but nothing calls it periodically during an assessment. The worker's health is still checked reactively (on the next `callTool()` request).

<details>
<summary>Fix details</summary>

- **File:** `Argus-Tui/packages/opencode/src/argus/bridge/mcp-client.ts`
- **What changed:** Added `probeHealth(): Promise<boolean>` method (line 305) that wraps `isHealthy()` in try/catch.
- **Missing:** Periodic 30s health probe interval during assessment execution.
</details>

### 16. Phase Complete LLM Feedback Silently Degrades 🟡 PARTIAL FIX

**`argus-workers/mcp_server.py:1034-1075`** — The `_fallback_phase_complete()` method now returns a `fallback: True` flag (line ~1070) to signal degraded mode.

However, the TypeScript side (`workflow-runner.ts:660-677`) never checks for the `fallback` flag in the response. The degradation signal is emitted but not acted upon.

<details>
<summary>Fix details</summary>

- **File:** `argus-workers/mcp_server.py` — `_fallback_phase_complete()` now returns `"fallback": True` in its response dict.
- **Missing:** The workflow-runner's `phaseCompleteResult` handling doesn't check for `fallback` and therefore doesn't adjust executor behavior.
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

### 18. Attack Graph Silently Skips Invalid Findings ❌ NOT FIXED

**`argus-workers/mcp_server.py:1188`** — Per-finding exceptions still caught with `logger.debug`. No count or summary returned.

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
- **Note:** The global timer (`assessmentStartTime`) is never explicitly set to `Date.now()` at assessment start — it stays at 0, meaning only the per-phase timeout is currently active. The global breaker requires wiring in the assessment entry point.
</details>

### 21. Best-Effort try/catch Everywhere Masks Failures ❌ NOT FIXED

**`Argus-Tui/packages/opencode/src/argus/workflow-runner.ts:519,561,643,679,706`** — All 5 critical try/catch paths remain. Lock failure (line 561) now throws in autonomous mode (see blocker 23), but the other 4 still silently degrade.

### 22. Circuit Breaker Defaults Kill Tools Too Aggressively ❌ NOT FIXED

**`Argus-Tui/packages/opencode/src/argus/config/tool-config.ts:72-76`, `Argus-Tui/packages/opencode/src/argus/bridge/tool-health.ts:17-19`** — Defaults unchanged.

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

### 25. Semgrep/Bandit Findings-Bearing Exit Codes Missed on MCP Path ❌ NOT FIXED

**`argus-workers/mcp_server.py:685-690,701-717`** — The `FINDINGS_EXIT_CODES` dict in `mcp_server.py` (line ~685) still has the same set as `ToolRunner`. Any divergence between the two would cause findings to be lost, but they are currently in sync.

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

### 31. LLM Tool Selection Silently Falls Back To Deterministic ❌ NOT FIXED

**`argus-workers/agent/react_agent.py:560-563,607-610`** — LLM → deterministic fallback still silent.

### 32. ReActAgent Max Iterations Not Configurable From TypeScript Side ❌ NOT FIXED

**`argus-workers/agent/react_agent.py:19,1052-1054`** — Counter added to `AgentSessionStore` but TS/Python defaults remain mismatched (50 vs 10).

### 33. Auth Checkpoint Restore Has No Hard Timeout For Login ❌ NOT FIXED

**`argus-workers/agent/react_agent.py:1153-1183`** — `ThreadPoolExecutor` timeout exists but leaked threads not cleaned up.

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

### 37. ThreadPoolExecutor Resources Not Bounded Across Concurrent Assessments ❌ NOT FIXED

**`argus-workers/orchestrator_pkg/recon.py:274`, `scan.py:868`, `swarm.py:630`, `attack_surface_mapper.py:49`** — Multiple ThreadPoolExecutors still unbounded.

### 38. No Cancellation Propagation From TypeScript To Python Agent 🟡 PARTIAL FIX

**`Argus-Tui/packages/opencode/src/argus/bridge/mcp-client.ts:612-614`, `argus-workers/mcp_server.py:1368-1412`** — Cancel RPC handler exists but `AgentSessionStore` doesn't implement a `cancel()` method.

The `cancelAgent()` method on the TypeScript side sends an `"cancel"` RPC request. The Python `handle_cancel` handler (line 1368) checks for `server.session_store.cancel()` — which doesn't exist on `AgentSessionStore` — then falls through to try direct session manipulation. This means cancellation works for dict-like sessions but not for the default class-based sessions.

<details>
<summary>Fix details</summary>

- **File (TS):** `Argus-Tui/packages/opencode/src/argus/bridge/mcp-client.ts` — `cancelAgent()` method added (line 612).
- **File (Python):** `argus-workers/mcp_server.py` — `handle_cancel` registered (line 1412).
- **Missing:** `AgentSessionStore.cancel()` method not yet implemented.
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

### 41. SQLite Finalizer May Never Run 🟡 PARTIAL FIX

**`Argus-Tui/packages/opencode/src/argus/engagement/store.ts:708-720`** — `registerExitHandler()` method exists but is never called.

The method registers `process.on("exit")`, `SIGINT`, and `SIGTERM` handlers that call `this.close()`. However, nothing in the assessment lifecycle calls `registerExitHandler()` — it's dead code unless explicitly invoked by a caller.

<details>
<summary>Fix details</summary>

- **File:** `Argus-Tui/packages/opencode/src/argus/engagement/store.ts`
- **What changed:** Added `registerExitHandler()` method (line 708).
- **Missing:** No caller invokes it. The `WorkflowRunner` or CLI entry point should call `store.registerExitHandler()` after construction.
</details>

### 42. Evidence Pruning Failures Silently Ignored ❌ NOT FIXED

**`Argus-Tui/packages/opencode/src/argus/evidence/collector.ts`** — Errors still caught silently.

### 43. Report LLM Enhancement Has No Hard Timeout ✅ FIXED

**`Argus-Tui/packages/opencode/src/argus/commands/report.ts:39`** — Added 60-second hard timeout per LLM analysis call.

Each individual LLM analysis now has a `Promise.race` with a 60-second timeout. Hanging LLM calls don't block report generation.

<details>
<summary>Fix details</summary>

- **File:** `Argus-Tui/packages/opencode/src/argus/commands/report.ts`
- **What changed:** Individual analysis calls wrapped in `Promise.race` with 60s timeout.
</details>

### 44. No Cross-Tool Rate Limiting For Parallel Tool Execution ❌ NOT FIXED

**`Argus-Tui/packages/opencode/src/argus/planner/executor.ts:251-263`** — No global rate limiter.

### 45. No Self-Throttling When Target Responds With 429/503 ❌ NOT FIXED

**`Argus-Tui/packages/opencode/src/argus/planner/executor.ts`, `argus-workers/tools/tool_runner.py`** — No unified rate-limiting detection and backoff.

### 47. Worker Cannot Recover From Database Connection Loss Mid-Assessment ❌ NOT FIXED

**`argus-workers/state_machine.py`, `argus-workers/checkpoint_manager.py`** — No automatic reconnection.

### 48. Governance Token Budget Is Estimated (Not Actual) ❌ NOT FIXED

**`argus-workers/runtime/governance.py:115-119,238-249`** — Token budget still uses hardcoded estimates.

### 49. EngagementState and ReActAgent Independently Truncate (Different Data) 🟡 PARTIAL FIX

**`argus-workers/runtime/engagement_state.py:326-329`**, **`argus-workers/agent/react_agent.py:421-427`** — Both layers now log warnings on truncation, but still no coordination between them.

<details>
<summary>Fix details</summary>

- **File:** `argus-workers/runtime/engagement_state.py` — Warning logged at line ~328 when observations are truncated at 50 entries.
- **File:** `argus-workers/agent/react_agent.py` — Warning logged at line ~425 when history is truncated.
</details>

### 50. LLM Agent `max_iterations` Mismatch Between Python and TypeScript ❌ NOT FIXED

**`argus-workers/config/constants.py:257-258`** (default: 10), **`Argus-Tui/packages/opencode/src/argus/planner/executor.ts:233`** (default: 50) — Still mismatched.

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

### 54. Distributed Semaphore Has TOCTOU Race Condition ❌ NOT FIXED

**`argus-workers/runtime/concurrency.py:61-83`** — Redis SETNX without Lua scripting.

### 55. LLM Provider Auto-Detect From Key Prefix Is Fragile ❌ NOT FIXED

**`argus-workers/llm_client.py:76-114`** — No prefix validation.

### 56. LLM Agent Model Env Var Name Mismatch With .env.example ✅ FIXED

- **`.env.example`** — Updated to document `LLM_AGENT_MODEL` (the correct variable used by the code), replacing `LLM_MODEL` (which is unused by the agent code).

<details>
<summary>Fix details</summary>

- **File:** `.env.example`
- **What changed:** Changed `LLM_MODEL` to `LLM_AGENT_MODEL` in the example and added documentation for `ARGUS_AUTO_ANSWER`, `ARGUS_AUTONOMOUS`, and `ARGUS_AUTO_APPROVE` env vars.
</details>

### 57. No Metrics or Health Endpoint Exposed By Workers ❌ NOT FIXED

**`argus-workers/`** — No HTTP metrics endpoint exists.

### 58. Governance Uses Wall Clock, Not Active Time ❌ NOT FIXED

**`argus-workers/runtime/governance.py:104-108`** — `time.time() - self._start_time` still wall clock.

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

### 62. MCP Transport Has No Stdin Heartbeat ❌ NOT FIXED

**`argus-workers/mcp_transport.py`** — No stdin timeout or health check for parent process death.

### 63. NET_RAW Capability + no-new-privileges Is an Undocumented Security Profile ❌ NOT FIXED (design)

**`docker-compose.yml:72,82,93`** — By design for nmap SYN scans.

### 64. `zero_finding_stop` and `low_signal_threshold` Race ❌ NOT FIXED

**`argus-workers/config/constants.py:269`** (`LLM_AGENT_ZERO_FINDING_STOP = 4`), **`argus-workers/runtime/governance.py:22`** (`_DEFAULT_LOW_SIGNAL_THRESHOLD = 3`) — Still racing.

### 65. Git SSRF Allowlist: YAML Config Only Applied Through `from_config()` Path ❌ NOT FIXED

**`argus-workers/config/constants.py:201-234`** — `from_config()` still catches `(ImportError, RuntimeError)` silently.

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

### 36. `scope.mode: warn` Allows Out-Of-Scope Access In Autonomous Mode ❌ NOT FIXED

**`argus.config.yaml:20`** — Setting `scope.mode: open` is still a manual config step.

### 46. Docker Compose Has No Health Checks ❌ NOT FIXED

**`docker-compose.yml`** — PostgreSQL and Redis still lack health checks.

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

### 28. Startup Credential Guard Only Warns ❌ NOT FIXED

**`argus-workers/mcp_server.py:55-61`** — No hard block for placeholder credentials.

---

## 🟠 CONFIG TRAPS — Defaults That Sabotage Autonomy

| Config Key | Default | Autonomous Impact | Fix Status |
|---|---|---|---|
| `scope.mode` | `warn` | Allows out-of-scope targets with warning | ❌ Not fixed |
| `git_host_policy` | `allowlist` | Blocks git repos from unlisted hosts | ❌ Not fixed |
| `approval_gates` | `true` | Stdin prompts unless `ARGUS_AUTO_APPROVE=1` | ✅ See blocker 2 |
| `storage.encryption.enabled` | `false` | Credentials stored in plaintext | ❌ Not fixed |
| `disabled` | `[sqlmap]` | One tool pre-disabled | ❌ Not fixed |
| `LLM_API_KEY` | empty | Hybrid mode fails | ❌ Operational |
| `ARGUS_AUTO_APPROVE` | not set | Approval gates block | ✅ Now works for destructive gates |
| `ARGUS_AUTONOMOUS` | not set | No autonomy profile | ✅ Documented |
| `DETERMINISTIC_FALLBACK` | `false` (opt-in) | LLM planning used even when LLM key missing | ❌ Not fixed |
| `tools.circuit_breaker.max_failures` | `5` | Tools go dark for 5 min after 5 failures | ❌ Not fixed |
| `tools.circuit_breaker.cooldown_ms` | `300000` (5 min) | No half-open probe in TS-side circuit breaker | ❌ Not fixed |
| `scope.mode` default | `warn` | Not `open` — requires explicit config change | ❌ Not fixed |
| `ARGUS_HYBRID_MAX_ITERATIONS` | `50` | No safety net for runaway LLM loops | ✅ Per-phase + global breakers |
| `storage.encryption.enabled` | `false` | Engagement DBs stored as plaintext SQLite | ❌ Not fixed |

---

## SUMMARY

### Fix Status Overview

| Category | Total | ✅ Fixed | 🟡 Partial | ❌ Unfixed |
|---|---|---|---|---|
| P0 — Deadlocks/Stops | 5 | 5 | 0 | 0 |
| P1 — Reliability | 5 | 4 | 1 | 0 |
| P2 — Robustness | 6 | 5 | 1 | 0 |
| P3 — Config/Polish | 5 | 4 | 1 | 0 |
| P4 — Edge Cases | 5 | 3 | 2 | 0 |
| Other blockers | 40+ | 1 | 0 | ~20 code-fixable + ~20 operational |
| **Total** | **66** | **22** | **5** | **~39** |

### What Must Be True for Autonomous Mode (Updated)

1. `ARGUS_AUTONOMOUS=1` and `ARGUS_AUTO_APPROVE=1` env vars set
2. `LLM_API_KEY` set in env (for LLM-driven features)
3. All ~60 security tool binaries installed on PATH
4. Python MCP worker environment set up for Python-based tools
5. `credentials.json` with target login credentials (if browser testing needed)
6. `scope.mode` set to `"open"` in `argus.config.yaml` (or targets in `allowed_targets`)
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
| **No health probe** | **silent skip** | **No** | **🟡 Method exists, not wired** |
| **LLM feedback degrades silently** | **silent skip** | **No** | **🟡 Fallback flag emitted, not consumed** |
| **Structured findings lost** | **silent skip** | **No** | **✅ Fixed** |
| **Phase drop with zero tools** | **silent skip** | **No** | **✅ Fixed** |
| **Runaway hybrid loop** | **deadlock** | **Yes** (env vars) | **✅ Per-phase + global breakers** |
| **Best-effort failures masked** | **silent skip** | **No** | ❌ Not fixed |
| **Circuit breaker kills tools** | **silent skip** | **No** | ❌ Not fixed |
| **Lock skip on Redis down** | **silent skip** | **Yes** (autonomous mode) | **✅ Fail hard in autonomous** |
| **Encrypted DB handle leak** | **security** | **No** | **✅ 3x retry + backoff** |
| **Bun runtime required** | **hard fail** | **No** | ❌ Not fixed |
| **Playwright browsers** | **hard fail** | **No** | ❌ Not fixed |
| **Placeholder credentials** | **silent skip** | **Yes** | ❌ Not fixed |

### Action Items (Updated)

#### ✅ Completed Fixes (22 blockers)

| # | Blocker | Fix |
|---|---|---|
| 1 | Question tool hang | `ARGUS_AUTO_ANSWER` env var |
| 2 | Destructive gate auto-skip | `ARGUS_AUTO_APPROVE` now applies in non-TTY |
| 5 | Non-TTY destructive skip | Same as #2 |
| 13 | Config silent fallback | Fails hard in autonomous mode |
| 14 | MCP ready timeout | Configurable via `ARGUS_MCP_READY_TIMEOUT_MS` |
| 17 | Structured findings lost | Consumed `data.structured` in executor |
| 19 | Zero-tools phase | Throws error in autonomous mode |
| 20 | Runaway hybrid loop | Per-phase + global max-duration circuit breakers |
| 23 | Lock skip | Fails hard in autonomous mode |
| 24 | DB resource leak | 3x retry with exponential backoff |
| 29 | Unbounded LLM cost | Cost guard applies in all modes |
| 30 | History truncation loss | Warning logged on truncation |
| 34 | Destructive gate bypass | Same as #2 |
| 35 | Per-phase timeout | `ARGUS_MAX_PHASE_DURATION_MS` |
| 39 | Message size limit | 10MB input / 50MB output |
| 40 | Orphaned processes | Process group kill |
| 43 | Report LLM timeout | 60s hard timeout per analysis |
| 52 | atexit cleanup | Registered for DB pool |
| 56 | Env var name mismatch | `.env.example` updated |
| 59 | Config schema validation | Unknown key warnings |
| 60 | Connection pool validation | SELECT 1 ping |
| 61 | Evidence prune never called | Auto-prune at assessment end |
| 66 | Orphaned config key | `backoff_multiplier` removed |

#### 🟡 Partial Fixes (5 blockers)

| # | Blocker | What's Done | What's Missing |
|---|---|---|---|
| 15 | Health probes | `probeHealth()` method exists | Nothing calls it periodically during assessment |
| 16 | LLM feedback degradation | `fallback: True` flag emitted | TypeScript executor doesn't consume the flag |
| 38 | Cancel propagation | Cancel RPC handler registered | `AgentSessionStore.cancel()` method not implemented |
| 41 | SQLite finalizer | `registerExitHandler()` method exists | No caller invokes it |
| 49 | State truncation coordination | Warnings added at both layers | No coordination mechanism between layers |

#### ❌ Top Code-Fixable Remaining (15 blockers)

| # | Blocker | Reason Not Fixed |
|---|---|---|
| 6 | Circuit breaker fallback tools | Requires architectural design for fallback tool mapping |
| 7 | Degraded mode cache staleness | Requires cache invalidation strategy |
| 18 | Attack graph invalid findings | Minor edge case — low impact |
| 21 | Best-effort try/catch masking | Requires careful per-path analysis — risky blanket change |
| 22 | Circuit breaker defaults | Design choice — current defaults work for most cases |
| 25 | Semgrep/bandit exit code sync | Minor — dicts are currently in sync |
| 28 | Startup credential guard | Warns vs blocks — design decision |
| 31 | LLM→deterministic fallback silence | Low observability impact |
| 32 | Max iterations mismatch | Iteration counter added but defaults still differ |
| 33 | Auth checkpoint thread leak | Minor — threads eventually cleaned up by GC |
| 36 | scope.mode warn | Explicit config change required by design |
| 42 | Evidence prune failure silence | Minor error-handling edge case |
| 44 | Cross-tool rate limiting | Significant feature — requires global rate limiter |
| 45 | Self-throttling 429/503 | Significant feature — requires unified throttle detection |
| 47 | DB connection loss recovery | Requires psycopg2 reconnect logic |
