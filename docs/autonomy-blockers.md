# Autonomy Blockers — Full Audit

What prevents Argus from running fully autonomously (no human in the loop).

---

## 🔴 DEADLOCKS — Execution Halts Indefinitely

### 1. Question Tool Has No Auto-Answer

**`Argus-Tui/packages/opencode/src/tool/question.ts:14-43`**

The LLM can decide to `call_tool("question", ...)` to ask the user something mid-assessment. This tool reads from stdin with **no timeout, no auto-response, and no env-var bypass**. If triggered in headless/autonomous mode, the entire assessment hangs forever.

`ARGUS_AUTO_APPROVE` does **not** cover it. No mitigation exists.

### 2. Approval Gates Block Without TTY

**`Argus-Tui/packages/opencode/src/argus/workflows/approval.ts:75-102`**

Three hardcoded gates (`destructive_tools`, `auth_testing`, `privilege_escalation`) prompt stdin with a **30-second timeout**. In non-TTY mode, destructive gates are **silently skipped** (not auto-approved — silently denied). This means destructive-tool phases in `full_assessment.yaml`, `xss.yaml`, `priv-esc.yaml` never execute.

Fixable via `ARGUS_AUTO_APPROVE=1`, but only for non-destructive gates. Destructive tools require a TTY or they are silently dropped.

### 3. Target Confirmation Blocks

**`Argus-Tui/packages/opencode/src/argus/workflow-runner.ts:376-408`**

When `security.scope.require_confirmation` is set, prompts stdin for 30s. Non-TTY auto-confirms, but this is a config trap — default is off, but if toggled, headless mode stalls.

---

## 🟡 SILENT SKIPS — Capability Lost Without Notice

### 4. ~60 External Binaries Must Be Pre-Installed

**`argus-workers/mcp_server.py:312-317`**

Every tool (nuclei, nmap, semgrep, gitleaks, trivy, subfinder, httpx, katana, dalfox, ffuf, nikto, whatweb, wpscan, commix, amass, gospider, masscan, etc.) is registered at MCP startup. If missing, the YAML loader skips it with a `logger.warning()` — assessment proceeds with zero tools and reports 0 findings.

The `argus doctor` command lists missing tools but the runtime never fails or warns during an assessment.

### 5. Non-TTY Destructive Gates Auto-Skip

**`Argus-Tui/packages/opencode/src/argus/workflows/approval.ts:92-96`**

In non-TTY mode (which includes many headless CI/CD setups), `process.stdout.isTTY` is `false`, so destructive approval gates return `"Non-TTY — destructive gate auto-skipped"`. The phase runs with no tools.

### 6. Tool Health Monitor — Circuit-Breaker Skips

**`Argus-Tui/packages/opencode/src/argus/bridge/tool-health.ts`, `Argus-Tui/packages/opencode/src/argus/planner/executor.ts:494-495`**

After 5 consecutive failures, a tool's circuit breaker opens for 5 minutes. The executor silently skips it with a `console.log`. No fallback tool is attempted. In autonomous mode with no operator watching logs, all tools can go dark one by one.

### 7. Degraded Mode Caches Stale Results

**`Argus-Tui/packages/opencode/src/argus/bridge/mcp-client.ts:44-49`, `Argus-Tui/packages/opencode/src/argus/bridge/supervisor.ts:25`**

After 3 worker restarts, the `WorkerSupervisor` enters degraded mode. The `WorkersBridge` serves cached results (5-min TTL) for survived tools. A human operator would notice; an autonomous run gets stale data silently.

### 13. Config File Loading Errors Silently Fall Back

**`Argus-Tui/packages/opencode/src/argus/workflow-runner.ts:542-549`, `Argus-Tui/packages/opencode/src/argus/config/feature-flags.ts:220-227`**

3 try/catch blocks silently swallow config file loading errors (`argus.config.yaml`, `~/.argus/config.yaml`):

1. `workflow-runner.ts:542-549`: Feature flag + replan config loads with `catch { console.warn("Config file missing or invalid, using defaults") }` — a malformed YAML silently defaults everything.
2. `feature-flags.ts:220-227`: `loadFromUserConfig()` catches all errors with `console.warn`.
3. `tool-config.ts:39-40`: `ToolConfig.load()` catches per-file errors with `console.warn`.

In autonomous mode, a single typo in `argus.config.yaml` silently resets ALL features to defaults, including potentially disabling critical features like `workflow_registry` or `approval_gates`.

### 14. MCP Worker Ready-Timeoute Too Short

**`Argus-Tui/packages/opencode/src/argus/bridge/mcp-client.ts:270-281`**

`waitForReady()` uses a fixed 10-second total timeout with exponential backoff starting at 200ms. On cold start (first run, dependency installation, Docker cold boot), the Python MCP worker can easily exceed 10s to start. The bridge throws "MCP worker failed to become ready" and the entire assessment fails.

No automatic retry at the workflow-runner level. No configurable timeout.

### 15. No MCP Worker Health Probe During Assessment

**`Argus-Tui/packages/opencode/src/argus/bridge/mcp-client.ts`**

After the initial `connect()`, there is zero proactive health monitoring of the MCP worker process. If the worker crashes mid-phase, the error surfaces only on the next `callTool()` request. By that time, multiple pending requests may have already been rejected.

The `WorkerSupervisor` restart mechanism is reactive (triggered on `exit` event), not proactive.

### 16. Phase Complete LLM Feedback Silently Degrades

**`argus-workers/mcp_server.py:1034-1075`**

When `handle_phase_complete()` fails — whether because the LLM is unavailable, an exception occurs, or any other reason — it silently falls through to `_fallback_phase_complete()`. The TypeScript side (`workflow-runner.ts:643`) labels this as "best-effort — failures don't block the assessment" and labels it with a warning emit. But the fallback `phase_map` is a hardcoded dict with no awareness of actual assessment context. The LLM's reasoning is completely replaced with a template string.

In autonomous mode, the assessment continues but receives non-contextual guidance for every phase transition, silently reducing assessment quality.

### 17. Structured Findings From MCP Path Are Lost

**`argus-workers/mcp_server.py:701-717`, `Argus-Tui/packages/opencode/src/argus/planner/executor.ts:502-535`**

The MCP server's `call_tool()` dispatches structured parsing via `dispatch()` and stores results in `mcp_result.data["structured"]`. However, the TypeScript executor (`executor.ts`) only checks `result.data` for raw arrays or strings. The `structured` key is never consumed. All structured, typed findings with proper severity, CWE, and evidence are bypassed.

Autonomous assessments get raw text placed into `description` fields rather than properly normalized findings.

### 18. Attack Graph Silently Skips Invalid Findings

**`argus-workers/mcp_server.py:1188`**

`handle_get_attack_graph()` iterates findings and catches per-finding exceptions with `logger.debug("Skipping invalid finding in attack graph: %s", e)`. No count or summary is returned. The TypeScript side (`workflow-runner.ts:706`) treats the entire call as "best-effort." If ALL findings fail validation, the attack graph returns empty chains with no error.

### 19. Planner Silently Drops Phases With Zero Tools

**`Argus-Tui/packages/opencode/src/argus/planner/planner.ts:79,114`**

When `selectBest()` returns zero tools for a phase's required capabilities, the planner writes a stderr warning but silently removes the phase. In a scenario where ALL external binaries are missing, the assessment runs zero phases and reports zero findings — with only stderr warnings that nobody sees in autonomous mode.

### 20. Runaway Phase Execution In Hybrid Mode

**`Argus-Tui/packages/opencode/src/argus/planner/executor.ts:231-234`**

The hybrid (LLM-driven) executor has a `while (!done)` loop with `maxIterations` defaulting to 50 via `ARGUS_HYBRID_MAX_ITERATIONS`. If the LLM keeps deciding to continue (tool after tool returning findings), the loop can run 50 iterations. Each iteration makes 3 MCP round-trips (agentNext + callTool + agentObserve). In a real assessment, this is 50+ sequential tool executions with no parallelization and no batch timeout.

No global max-duration circuit breaker. No cost budget enforcement.

### 21. Best-Effort try/catch Everywhere Masks Failures

**`Argus-Tui/packages/opencode/src/argus/workflow-runner.ts:519,561,643,679,706`**

At least 5 critical paths in the workflow runner use try/catch with silent degradation:

| Path | What Is Swallowed |
|---|---|
| `bridge.acquireEngagementLock()` | Distributed lock failure → proceeds without lock, risking concurrent assessments |
| `bridge.quickDriftCheck()` | MCP drift check → phase proceeds with potentially stale tool definitions |
| `bridge.phaseComplete()` | LLM-driven replanning feedback → phase continues with deterministic fallback |
| `bridge.getAttackGraph()` | Attack graph chain detection → replanning proceeds without chain awareness |
| Phase complete exception | All above → assessment continues with no context-aware guidance |

In autonomous mode, ALL of these silently degrade. The operator sees only a `⚠` emit that gets lost in tool output noise.

### 22. Circuit Breaker Defaults Kill Tools Too Aggressively

**`Argus-Tui/packages/opencode/src/argus/config/tool-config.ts:72-76`, `Argus-Tui/packages/opencode/src/argus/bridge/tool-health.ts:17-19`**

Default: 5 consecutive failures → circuit open for 300 seconds (5 minutes). For security tools run against real targets:
- Target rate-limits → 5 tools get rate-limited → circuit opens → tools shut down for 5 minutes
- Transient network blip → all concurrent parallel tools fail → multiple circuits open
- No half-open probe mechanism in the TS-side ToolHealthMonitor (unlike the Python LLMClient which has proper half-open semantics)

When the circuit breaker is on the MCP bridge level (mcp-client.ts:337), ALL LLM-related tools fail — not just the problematic tool.

### 23. Engagement Lock Acquisition Silently Skipped

**`Argus-Tui/packages/opencode/src/argus/workflow-runner.ts:561-565`**

`const lockedEngagement = await bridge.acquireEngagementLock(engagementId).catch(() => ({ acquired: false }))`

When Redis is unavailable, the lock is silently skipped. Multiple concurrent assessments on the same target can race on database state, findings, and attack graph data. No alert, no retry, no queuing.

### 24. Per-Engagement DB Resource Leak On Close Failure

**`Argus-Tui/packages/opencode/src/argus/engagement/store.ts:645,657`**

Close failures for encrypted DB handles are caught with `/* best-effort */`. If `encryptedHandle.close()` fails, the temporary decrypted SQLite file may remain on disk with plaintext engagement data. No retry, no alert, no secure cleanup fallback.

### 25. Semgrep/Bandit Findings-Bearing Exit Codes Missed on MCP Path

**`argus-workers/mcp_server.py:685-690,701-717`**

The MCP server's `call_tool()` uses `subprocess.run()` directly, NOT `ToolRunner`. The `ToolRunner` has `FINDINGS_EXIT_CODES` handling for tools like semgrep, bandit, gitleaks that exit non-zero when vulnerabilities are found. The MCP `call_tool()` mirrors this with its own `FINDINGS_EXIT_CODES` dict — but any mismatch between the two will cause tools to report failure when they actually found findings.

At runtime, `nuclei` (exit 1 on finding) is handled correctly, but if any new tool is added to only one dict, findings are silently lost.

---

## 🟡 SILENT SKIPS (Continued)

### 29. ReActAgent Has Unbounded LLM Cost In Autonomous Mode

**`argus-workers/agent/react_agent.py:859-885`**

The `ReActAgent` has a cost guard (`LLM_AGENT_MAX_COST_USD`) but it only runs in the legacy branch (when `GOVERNANCE_V2` feature flag is off). When `GOVERNANCE_V2` is enabled — which is the default for autonomous mode — cost is tracked but the legacy guard is skipped. The `governance.check()` call may or may not enforce cost limits depending on governance configuration.

In autonomous mode with no operator monitoring costs, LLM spend can run up unboundedly. Multiple concurrent autonomous assessments compound this risk.

### 30. Agent History Silently Truncated At 50 Entries

**`argus-workers/agent/react_agent.py:421-427`**

`self.history[-50:]` silently drops the oldest entries when the history exceeds 50. The LLM loses context of earlier tool results, potentially leading to:
- Repeated tool selections (same tool already tried but forgotten)
- Poor phase transition decisions (missing earlier recon context)
- Inability to detect patterns across the full assessment timeline

No warning is emitted when entries are dropped.

### 31. LLM Tool Selection Silently Falls Back To Deterministic

**`argus-workers/agent/react_agent.py:560-563,607-610`**

When `_call_llm_for_action()` fails for any reason (LLM unavailable, JSON parse error, hallucinated tool name), it returns `None`. The caller `plan_next_action()` silently falls through to `_deterministic_plan()`. The MCP server and TypeScript executor never know the assessment switched to degraded mode.

An entire phase can run with deterministic tool selection while the operator believes the LLM is driving decisions.

### 32. ReActAgent Max Iterations Not Configurable From TypeScript Side

**`argus-workers/agent/react_agent.py:19,1052-1054`**

The Python `ReActAgent` reads `LLM_AGENT_MAX_ITERATIONS` from a Python constant. The TypeScript executor has its own `maxIterations` (default 50 from `ARGUS_HYBRID_MAX_ITERATIONS`). These two limits are completely independent — the TypeScript side can stop sending requests while the Python agent continues waiting, or vice versa.

No coordination mechanism exists between the two runtime environments.

### 33. Auth Checkpoint Restore Has No Hard Timeout For Login

**`argus-workers/agent/react_agent.py:1153-1183`**

The auth checkpoint restore path uses a `ThreadPoolExecutor` with a 30-second timeout. If `run_login()` hangs (network issues, target unresponsive), the `login_future.result(timeout=30)` catches this, but the underlying thread and HTTP session continue running in the background. Leaked threads accumulate across retries.

No cleanup of the abandoned thread/HTTP session after timeout.

### 35. No Per-Phase Timeout In Workflows

**`Argus-Tui/packages/opencode/src/argus/workflows/full_assessment.yaml`**

The YAML workflow has no per-phase timeout configuration. If a single tool in a parallel phase hangs (e.g., nuclei waiting for a non-responsive target), the `Promise.all` in `executor.ts` waits indefinitely. The only safeguard is the per-tool timeout in `tool-definitions.yaml`, but these are tool-specific, not phase-specific.

No global phase timeout means a single hung tool blocks the entire assessment.

### 37. ThreadPoolExecutor Resources Not Bounded Across Concurrent Assessments

**`argus-workers/orchestrator_pkg/recon.py:274`, `argus-workers/orchestrator_pkg/scan.py:868`, `argus-workers/agent/swarm.py:630`, `argus-workers/tools/attack_surface_mapper.py:49`**

Multiple `ThreadPoolExecutor` instances create thread pools for parallel tool execution:
- `recon.py`: `max_workers=8`
- `scan.py`: `max_workers=5`
- `swarm.py`: pool per agent (unbounded)
- `attack_surface_mapper.py`: `max_workers=3`
- `web_scanner.py`: `max_workers=6`
- `intelligence_engine.py`: `max_workers=10`

None of these pools check available system resources before spawning threads. When running multiple concurrent assessments (which the distributed lock should prevent but silently skips), thread counts can exhaust system limits. No unified thread pool or resource manager exists.

### 38. No Cancellation Propagation From TypeScript To Python Agent

**`Argus-Tui/packages/opencode/src/argus/planner/executor.ts:231-381`, `argus-workers/agent/react_agent.py:366-370`**

The `ReActAgent.cancel()` method sets a flag (`self._cancelled = True`) that the run loop checks at the start of each iteration. However, the TypeScript executor has no mechanism to call this method. If the TypeScript side decides to stop (phase complete, error, user interrupt), the Python agent continues running its current tool execution and only stops on the next iteration check.

This means tool execution continues for potentially minutes after the TypeScript side has decided to halt.

### 39. MCP Transport Has No Message Size Limit

**`argus-workers/mcp_transport.py`**

The JSON-RPC transport reads entire lines from stdin without size limits. A tool producing a massive output (e.g., nuclei scanning a large scope, web_scanner with thousands of endpoints) could produce JSON response lines that exceed available memory.

No streaming or chunked response handling exists.

### 40. Worker Cleanup On Abnormal Exit Leaks Child Processes

**`Argus-Tui/packages/opencode/src/argus/bridge/mcp-client.ts:108-122`**

The signal forwarding sends `SIGTERM` to the MCP worker process. If the worker doesn't terminate within 3 seconds, `SIGKILL` is sent. However, the MCP worker may have spawned grandchild processes (nuclei, nmap, sqlmap subprocesses). These are NOT cleaned up by the parent's termination — they become orphaned processes.

In autonomous mode running 50+ sequential tool executions, orphaned processes accumulate and consume system resources.

### 41. SQLite Finalizer May Never Run

**`Argus-Tui/packages/opencode/src/argus/engagement/store.ts:295`**

The `FinalizationRegistry` for the root SQLite DB handle is best-effort — it may never be called by the garbage collector, especially in short-lived CLI processes. If `close()` is not called explicitly before process exit, the WAL journal may contain uncheckpointed data.

No explicit `process.on('exit')` handler ensures clean shutdown.

### 42. Evidence Pruning Failures Silently Ignored

**`Argus-Tui/packages/opencode/src/argus/evidence/collector.ts`**

Evidence pruning (retention enforcement, size limits) catches all errors silently. If disk space is exhausted or files can't be deleted, the evidence directory grows unbounded. In autonomous mode with repeated assessments, evidence accumulates until disk is full.

No hard quota enforcement at the filesystem level.

### 43. Report LLM Enhancement Has No Hard Timeout

**`Argus-Tui/packages/opencode/src/argus/commands/report.ts:39`**

Report enhancement uses `Promise.allSettled()` to analyze findings with the LLM. If one LLM call hangs (network issue, provider rate limit), the entire report generation blocks until the timeout. The default LLM timeout is 30 seconds, but multiple sequential analysis calls can stack up to minutes.

In autonomous mode, report generation is the final phase — a hang here means all preceding work is not output.

### 44. No Cross-Tool Rate Limiting For Parallel Tool Execution

**`Argus-Tui/packages/opencode/src/argus/planner/executor.ts:251-263`**

The parallel executor runs up to 4 tools concurrently via `Promise.all(batch.map(...))`. Each tool independently sends requests to the target. There is no coordination between tools — nuclei can send 150 req/s while ffuf sends 200 req/s, overloading the target.

Individual tools have their own rate limiting (nuclei `-rate-limit`, ffuf `-rate`), but there's no global rate limiter that considers concurrent tools.

### 45. No Self-Throttling When Target Responds With 429/503

**`Argus-Tui/packages/opencode/src/argus/planner/executor.ts`, `argus-workers/tools/tool_runner.py`**

When tools receive HTTP 429 (Too Many Requests) or 503 (Service Unavailable), individual tools handle them differently: some retry, some fail, some skip. There's no unified mechanism to detect rate limiting from tool stderr/stdout and back off the entire assessment.

The `error_classifier.py` categorizes 429 as `RATE_LIMIT`, but this classification is only used for logging, not for throttling decisions.

### 47. Worker Cannot Recover From Database Connection Loss Mid-Assessment

**`argus-workers/state_machine.py`, `argus-workers/checkpoint_manager.py`**

The `EngagementStateMachine` and `CheckpointManager` use database connections from a pool. If the database connection drops mid-assessment (e.g., PostgreSQL restart, network blip), the database operations raise `psycopg2.Error` which propagates up through the call stack. The assessment fails with no automatic reconnection or retry.

No built-in database connection retry with exponential backoff exists outside the `llm_client.py`.

### 48. Governance Token Budget Is Estimated (Not Actual)

**`argus-workers/runtime/governance.py:115-119,238-249`**

The `Governance.check()` method enforces two budgets: a **cost budget** (reads actual `cost_usd` from the action object at line 97) and a **token budget** (uses `_estimate_token_usage()`). The token budget uses **hardcoded rough estimates** with a comment: "NOTE: These are rough estimates, not actual token counts." The estimates are per-tool-invocation guesses (nuclei=200, web_scanner=300, etc.), NOT actual LLM token counts.

The **cost guard IS based on real data** — it reads `action.get("cost_usd", 0.0)` from the action dict (line 97), which is populated by the LLM client with actual dollar costs. However, the **token budget** (checked at line 115) uses fabricated estimates. An LLM agent making real API calls with tens of thousands of tokens per invocation could far exceed the token limit before governance detects it.

In autonomous mode, the governance layer reports `total_tokens_estimated` with confidence, but this number is fictional.

### 49. EngagementState and ReActAgent Independently Truncate (Different Data)

**`argus-workers/runtime/engagement_state.py:326-329`**, **`argus-workers/agent/react_agent.py:421-427`**

Both `EngagementState.add_observation()` (line 326-329) and `ReActAgent._build_observation()` independently cap their history at 50 entries. However, they track **different data** — EngagementState tracks agent loop observations (role, content, timestamp), while ReActAgent tracks its own internal tool call/result history.

The concern is that these two layers have **no coordination** and **no warning** when entries are dropped. If observations flow through both systems independently, the effective window is 50 entries at each layer, but there's no mechanism to ensure the most important entries are preserved at either layer. In long assessments with 100+ tool calls, only the last 50 observations are available to the LLM, with the earliest context silently lost.

### 50. LLM Agent `max_iterations` Mismatch Between Python and TypeScript

**`argus-workers/config/constants.py:257-258`** (default: 10), **`Argus-Tui/packages/opencode/src/argus/planner/executor.ts:233`** (default: 50)

The Python `LLMAgentConfig.max_iterations` defaults to **10**, while the TypeScript `ARGUS_HYBRID_MAX_ITERATIONS` defaults to **50**. These are completely independent defaults with no coordination.

In practice, the Python `ReActAgent` will stop making decisions after 10 iterations while the TypeScript executor may keep sending `agentNext()` requests, receiving empty/stale responses. Conversely, if the TS executor stops early (e.g., after 20 iterations), the Python agent thinks it has 30 more iterations to go.

No coordination mechanism exists between the two runtime environments for iteration limits.

### 51. [RETRACTED — timeout IS passed to tool_runner.run()]

Re-verified against source: `execution_engine.py` line 145 explicitly passes `timeout=timeout` to `self.tool_runner.run()`. The timeout parameter IS forwarded. Whether ToolRunner respects it depends on ToolRunner's implementation, but ExecutionEngine does not ignore it.

### 52. Connection Pool Not Registered for atexit Cleanup

**`argus-workers/database/connection.py:317-325`**

The `ConnectionManager.close()` method exists but is **never registered** with `atexit`. If the process receives SIGTERM and the shutdown handler doesn't explicitly call `get_db().close()`, all pooled database connections leak.

No `atexit.register(get_db().close)` exists anywhere in the codebase. Compare with `orchestrator_pkg/orchestrator.py` which correctly registers atexit handlers, and `orchestrator_pkg/scan.py` which also has atexit cleanup. The database pool is the most critical resource to clean up, yet it has no atexit handler.

### 53. Docker Compose Override Enables Host Network Mode (Mitigated by Profiles)

**`docker-compose.override.yml`**

The override file enables `network_mode: host` for the worker container, giving it full host network access (sniff traffic, bind ports, access host-localhost services). 

**Mitigation:** The override is scoped behind `profiles: ["host-network"]`, meaning it is NOT auto-included with plain `docker compose up`. It requires explicit activation via `docker compose --profile host-network up` or `docker compose -f docker-compose.yml -f docker-compose.override.yml up`. This significantly reduces the risk of accidental inclusion.

However, if `COMPOSE_FILE` is set in the environment (e.g., in CI/CD scripts, developer shell profiles), a plain `docker compose up` WILL activate this override. The prominent security warnings in the file are the only defense.

### 54. Distributed Semaphore Has TOCTOU Race Condition

**`argus-workers/runtime/concurrency.py:61-83`**

The `DistributedSemaphore._acquire_redis()` method has a classic time-of-check-to-time-of-use (TOCTOU) race: it reads the current count via `r.get(key)`, then increments via `r.incr(key)`. Between these two operations, another worker can increment, causing the combined count to exceed `max_count`.

The code handles this by checking if the new count exceeds max and decrementing back, but during high contention multiple workers can overshoot simultaneously, each racing to decrement. This creates count drift over time.

Redis Lua scripting (`EVAL`) or `SETNX` with a sorted set would provide atomicity. The current SETNX-based approach is insufficient for correct distributed coordination under load.

### 55. LLM Provider Auto-Detect From Key Prefix Is Fragile

**`argus-workers/llm_client.py:76-114`**

The `LLMClient` auto-detects the provider from the API key prefix: `AIzaSy...` → Gemini, `sk-or-...` → OpenRouter, `sk-...` → OpenAI. This detection is done via simple string prefix checks.

If a user copies their key with trailing whitespace or a newline (extremely common copy-paste error), the prefix check fails. The key falls through to "generic" provider with no error or warning. The LLM client then makes API calls to an incorrect endpoint format, returning cryptic errors.

No key format validation exists. No whitespace trimming is applied before detection.

### 56. LLM Agent Model Env Var Name Mismatch With .env.example

**`.env.example:53`** (sets `LLM_MODEL=gemini-2.0-flash`), **`argus-workers/config/constants.py:260`** (reads `LLM_AGENT_MODEL`, defaults to `gpt-4o-mini`)

The `.env.example` file sets `LLM_MODEL` (without the `AGENT_` prefix), but the agent config reads `LLM_AGENT_MODEL`. The fallback is `gpt-4o-mini`. A user following the `.env.example` exactly will set `LLM_MODEL=gemini-2.0-flash`, but the agent will silently use `gpt-4o-mini` instead.

The general LLM config (`LLM_MODEL`) and agent-specific config (`LLM_AGENT_MODEL`) are different env vars with different defaults, but the example file only documents one of them, creating a config trap.

### 57. No Metrics or Health Endpoint Exposed By Workers

**`argus-workers/`**

The Celery workers, MCP server, and supporting infrastructure expose **no HTTP metrics endpoint** (no Prometheus `/metrics`, no health `/healthz`). In autonomous mode with no human operator watching logs, there is no way to:
- Monitor worker throughput or latency
- Detect crashed workers
- Track error rates over time
- Set up external alerting

The Docker HEALTHCHECK only checks Celery status, not the MCP server or database connectivity. A worker that's alive but unable to process tasks (e.g., stuck in an infinite retry loop) appears healthy.

### 58. Governance Uses Wall Clock, Not Active Time

**`argus-workers/runtime/governance.py:104-108`**

The governance runtime limit checks `time.time() - self._start_time` against `max_runtime_seconds` (default 3600s/1hr). This is **wall clock time**, not CPU time or active execution time.

If a tool spends 900 seconds waiting for an HTTP response (e.g., `asyncio.sleep` inside web_scanner), that counts against the runtime budget even though the worker isn't actually doing work. Conversely, a CPU-bound tool that maxes out the processor for 30 minutes only consumes 30 minutes of budget.

This means the runtime guard is ineffective: CPU-intensive assessments can run far longer than expected before hitting the wall clock limit, while I/O-waiting assessments are prematurely terminated.

### 59. Config Schema Is Not Validated At Startup

**`argus.config.yaml`**, **`Argus-Tui/packages/opencode/src/argus/config/loader.ts`**

The `argus.config.yaml` is loaded with `yaml.safe_load()` and processed with Zod in the TypeScript config loader. However, the resulting config dict is **not validated against a full schema** at startup. Unknown keys are silently ignored.

A configuration typo like `feature:` instead of `features:` or `rate_limiting:` (missing underscore) instead of `rate_limiting:` creates a dead config key. The user believes a feature is configured, but the key is silently dropped.

Compare with the Python side: `config_manager.py` uses `cm.get("tools.circuit_breaker.max_failures", ...)` which returns a default if the key doesn't exist. A typo here silently uses defaults.

### 60. Pool Connections Never Validated Before Use

**`argus-workers/database/connection.py:107-132`**

The `ConnectionManager._ensure_pool()` creates a `ThreadedConnectionPool` but **never validates connections** before returning them from `get_connection()`. A connection that was idle in the pool for hours (e.g., overnight between scheduled scans) could be stale — PostgreSQL may have closed it due to `idle_in_transaction_session_timeout` or network middleboxes may have dropped it.

No `SELECT 1` ping is performed before returning a connection from the pool. A stale connection silently fails on the first query with `psycopg2.InterfaceError`, which propagates up as a query failure, not a connection failure. The error is misclassified, and the assessment fails with no retry.

`psycopg2` has no built-in connection health check. A manual ping is required.

### 61. Evidence `pruneEngagement()` Exists But Is Never Called Automatically

**`Argus-Tui/packages/opencode/src/argus/evidence/collector.ts:113-124,131-178`**

The evidence collector has both:
1. A `checkStorageLimit()` method (line 113-124) that warns at 80% and 100% of `max_engagement_size_mb` (default 500MB), then returns `true`/`false`.
2. A `pruneEngagement()` method (line 131-178) with **full pruning logic** that deletes files older than `retention_days` and cleans up empty directories.

However, `pruneEngagement()` is **never called automatically** during the assessment lifecycle. The storage check triggers warnings but no automatic cleanup. Callers (like `saveRequest`, `saveResponse`, `captureScreenshot`) check storage limits and throw `"Storage limit exceeded"` errors, but no code path ever calls `pruneEngagement()`.

In autonomous mode, the prune logic exists but is dead code — evidence accumulates until disk is full or until an explicit manual prune is triggered.

### 62. MCP Transport Has No Stdin Heartbeat

**`argus-workers/mcp_transport.py`**

The MCP transport reads from stdin in a blocking loop (`sys.stdin.readline()`). If the parent process dies unexpectedly (SIGKILL, crash), stdin may not close properly in all scenarios. The transport has **no heartbeat, no stdin timeout, and no health check**.

In containerized environments where the parent process can be OOM-killed, the MCP server child process becomes an orphan that lives forever, consuming resources. The Celery app-level graceful shutdown handler (`shutdown_handler.py`) only handles signals — not unexpected parent death.

### 63. NET_RAW Capability + no-new-privileges Is an Undocumented Security Profile

**`docker-compose.yml:72,82,93`** (worker and celery-beat services)

Both worker services use `security_opt: no-new-privileges:true` AND `cap_add: NET_RAW`. These are **orthogonal** — `NET_RAW` grants raw socket access (needed for nmap SYN scans), while `no-new-privileges` prevents privilege escalation via suid binaries. They don't conflict, but the combination is unusual and undocumented.

The security implication: if nmap or any other tool is compromised through a scanning vulnerability, it can abuse raw sockets for arbitrary network operations. The `no-new-privileges` flag prevents full container breakout but doesn't prevent network abuse.

In autonomous mode, a vulnerable or malicious scan target could exploit this to pivot through the worker container's network access.

### 64. `zero_finding_stop` and `low_signal_threshold` Race

**`argus-workers/config/constants.py:269`** (`LLM_AGENT_ZERO_FINDING_STOP = 4`), **`argus-workers/runtime/governance.py:22`** (`_DEFAULT_LOW_SIGNAL_THRESHOLD = 3`)

The agent config says stop after 4 consecutive zero-finding iterations, but the governance layer has a low-signal threshold of 3. These are **two independent mechanisms** that race:
- Governance stops at 3 consecutive low-signal results
- Agent stops at 4 consecutive zero-finding iterations

Depending on which check runs first, the assessment stops at 3 or 4 iterations. The governance check runs before the agent iteration check, so governance effectively overrides the agent config. The operator who sets `zero_finding_stop: 10` would expect the agent to run 10 iterations, but governance would stop at 3.

No coordination or documentation of this interaction exists.

### 65. Git SSRF Allowlist: YAML Config Only Applied Through `from_config()` Path

**`argus-workers/config/constants.py:201-234`** (`GitSSRFConfig`)

The SSRF prevention for git clone has a hardcoded allowlist of ~15 trusted git hosts (github.com, gitlab.com, etc.). The `security.allowed_git_hosts` in `argus.config.yaml` extends this list when `GitSSRFConfig.from_config()` is called.

**Important:** In the normal code path (`CONFIG = ArgusConfig()` at line 301), the default factory IS `GitSSRFConfig.from_config`, which attempts to read from the ConfigManager. So the YAML config IS applied in the default instantiation path.

However, the YAML reading is **fragile**: `from_config()` catches `(ImportError, RuntimeError)` and silently falls back to hardcoded defaults (line 234). If the ConfigManager isn't available or the import chain fails, the YAML-configured `allowed_git_hosts` are silently ignored.

Also, `from_env()` (used when env vars override config) only reads from `ARGUS_ALLOWED_GIT_HOSTS` — it does NOT merge with YAML config. A mixed config (YAML + env var) would have the env var override silently replace the YAML config.

### 66. Rate Limiter Config Key `backoff_multiplier` Is Unused

**`argus-workers/config/config_manager.py:34`**

The config manager has a `backoff_multiplier: 2.0` setting that appears to be unused by any code path. The `rate_limiter.py` and `concurrency.py` use constants from `config/constants.py`. This orphaned config key has no effect — an operator who sets it expects rate limiting to be configured, but nothing changes.


---

## 🔴 DEADLOCKS (Continued)

### 34. LLM-Driven Phases Require Destructive Gate Bypass

**`Argus-Tui/packages/opencode/src/argus/workflows/full_assessment.yaml:22-34`**

Both `web_exploitation` and `api_exploitation` phases are marked `approval_gate: destructive_tools`. Without `ARGUS_AUTO_APPROVE=1`, these phases are silently skipped in non-TTY mode. In autonomous mode, the two most critical exploitation phases never execute unless `ARGUS_AUTO_APPROVE` is set — and even then, the destructive gate bypass only works for non-destructive gates in non-TTY mode.

### 43. Report LLM Enhancement Has No Hard Timeout

[Already listed above — consolidated]

---

## 🟠 CONFIG TRAPS — Defaults That Sabotage Autonomy (Continued)

### 36. `scope.mode: warn` Allows Out-Of-Scope Access In Autonomous Mode

**`argus.config.yaml:20`**

`scope.mode: warn` is the default. When set to `warn`, the target validator warns but does not block out-of-scope targets. The `executor.ts:487-492` scope check only blocks when `mode === "allowlist"`. In autonomous mode with no operator reading warnings, this is effectively no scope enforcement.

An autonomous assessment can proceed against any target, regardless of configuration.

### 46. Docker Compose Has No Health Checks

**`docker-compose.yml`**

PostgreSQL and Redis services have no health checks. If the MCP worker starts before the database is ready (first cold boot), connections fail and the worker crashes. The `start-argus.sh` script has a sleep-based wait, but there's no proper dependency health check.

In autonomous deployment scenarios, this race condition causes intermittent failures.

## 🔵 HARD DEPENDENCIES — Require Manual Setup

### 8. LLM API Key Required

**`.env.example:52`**

`LLM_API_KEY` is empty by default. Without it, hybrid/LLM-driven assessments fail at `LLMClient()` construction. The `_fallback_phase_complete` path takes over, which is deterministic and far less capable.

### 9. Browser MFA/CAPTCHA Cannot Be Automated

**`Argus-Tui/packages/opencode/src/argus/browser/login.ts:164-191`**

`detectAuthChallenge()` recognizes MFA, CAPTCHA, and OAuth/SSO challenges and returns structured info, but cannot solve them. The verifier returns `INFORMATIONAL` confidence with note: "MFA/CAPTCHA cannot be auto-solved."

Any target using multi-factor auth, CAPTCHA, or OAuth SSO blocks browser-based verifiers completely.

### 10. 17 Sensitive Env Vars Stripped From Subprocesses

**`argus-workers/mcp_server.py:661-683`**

All API keys (`OPENAI_API_KEY`, `AWS_SECRET_ACCESS_KEY`, etc.) are stripped from tool subprocesses. This is a security feature but means tools like `gitleaks`, `trivy`, and `semgrep` cannot use authenticated scans or private registries without explicit env passthrough.

### 11. Credential Store Requires Manual Setup

**`Argus-Tui/packages/opencode/src/argus/engagement/credentials.ts`**

Credentials for browser auth testing come from a `credentials.json` file, optionally encrypted with a master key. Neither file nor key is auto-generated. Browser verifiers (BOLA, PrivEsc, XSS) silently degrade without credentials.

### 12. PostgreSQL + Redis Required

**`docker-compose.yml`, `.env.example`**

Both must be running for engagement persistence, distributed locks, and dead-letter queues. No embedded/SQLite fallback.

### 26. Bun Runtime Required (bun:sqlite)

**`Argus-Tui/packages/opencode/src/argus/engagement/store.ts:1-14`**

The `EngagementStore` eagerly imports `bun:sqlite` via `createRequire`. This fails with a clear error under Node.js, but the store is used by the entire assessment pipeline. If running under Node (not Bun), the assessment crashes at `EngagementStore` construction.

No Node.js polyfill or SQLite fallback exists.

### 27. Playwright Browsers Required for Browser Verification

**`Argus-Tui/packages/opencode/src/argus/browser/engine.ts`**

Browser-based verifiers (XSS, BOLA, PrivEsc, SSRF, LFI, JWT, Secrets) require Playwright and its browser binaries. If `npx playwright install` hasn't been run, the verifiers fail at browser launch with a cryptic error rather than a clear diagnostic message.

No auto-install fallback, no graceful degradation path, no startup preflight check.

### 28. Startup Credential Guard Only Warns

**`argus-workers/mcp_server.py:55-61`**

`check_placeholder_credentials()` runs at startup and logs a warning if placeholder credentials are detected. The MCP server starts normally. An autonomous assessment proceeds with placeholder credentials that will fail at the first credential-requiring tool.

No hard block, no env-var bypass.

---

## 🟠 CONFIG TRAPS — Defaults That Sabotage Autonomy

| Config Key | Default | Autonomous Impact |
|---|---|---|
| `scope.mode` | `warn` | Allows out-of-scope targets with warning (not blocking) — safety issue |
| `git_host_policy` | `allowlist` | Blocks git repos from unlisted hosts |
| `approval_gates` | `true` | Stdin prompts unless `ARGUS_AUTO_APPROVE=1` |
| `storage.encryption.enabled` | `false` | Credentials stored in plaintext |
| `disabled` | `[sqlmap]` | One tool pre-disabled |
| `LLM_API_KEY` | empty | Hybrid mode fails |
| `ARGUS_AUTO_APPROVE` | not set | Approval gates block |
| `ARGUS_AUTONOMOUS` | not set | No autonomy profile |
| `DETERMINISTIC_FALLBACK` | `false` (opt-in) | LLM planning used even when LLM key might be missing |
| `tools.circuit_breaker.max_failures` | `5` | Tools go dark for 5 min after 5 failures — no graceful recovery |
| `tools.circuit_breaker.cooldown_ms` | `300000` (5 min) | No half-open probe in TS-side circuit breaker |
| `scope.mode` default | `warn` | Not `open` — requires explicit config change for autonomous |
| `ARGUS_HYBRID_MAX_ITERATIONS` | `50` | No safety net for runaway LLM loops |
| `storage.encryption.enabled` | `false` | Engagement DBs stored as plaintext SQLite files on disk |

---

## SUMMARY

### What Must Be True for Autonomous Mode

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
11. `argus.config.yaml` must be valid YAML — malformed files silently reset all features to defaults
12. `DETERMINISTIC_FALLBACK` should be set to `true` if no LLM key is available
13. `scope.mode` must be `"open"` — the default `"warn"` allows out-of-scope access

### Blocker Matrix

| Blocker | Type | Fixable via Env Var? | Fix Exists? |
|---|---|---|---|
| Question tool hang | deadlock | No | Not yet |
| Destructive gate silent skip | silent skip | Partial (TTY required) | Not yet |
| ~60 missing binaries | silent skip | No | Install them |
| No LLM key | hard fail | Yes | `LLM_API_KEY` |
| MFA/CAPTCHA | hard fail | No | Not possible |
| Approval gates | deadlock | Yes | `ARGUS_AUTO_APPROVE=1` |
| Target confirmation | deadlock | Yes | Non-TTY auto-confirms |
| PostgreSQL/Redis | hard fail | No | Must run infra |
| **Silent config fallback** | **silent skip** | **No** | **Fail on malformed config** |
| **MCP worker ready timeout** | **hard fail** | **No** | **Extendable timeout + retry** |
| **No health probe** | **silent skip** | **No** | **Periodic health check** |
| **LLM feedback degrades silently** | **silent skip** | **No** | **Signal degradation to executor** |
| **Structured findings lost** | **silent skip** | **No** | **Consume structured key** |
| **Phase drop with zero tools** | **silent skip** | **No** | **Fail or warn countably** |
| **Runaway hybrid loop** | **deadlock** | **Partial** | **`ARGUS_HYBRID_MAX_ITERATIONS`** |
| **Best-effort failures masked** | **silent skip** | **No** | **Reconsider try/catch boundaries** |
| **Circuit breaker kills tools** | **silent skip** | **No** | **Half-open probe + config** |
| **Lock skip on Redis down** | **silent skip** | **No** | **Hard fail or queue** |
| **Encrypted DB handle leak** | **security** | **No** | **Retry + audit** |
| **Bun runtime required** | **hard fail** | **No** | **Node polyfill** |
| **Playwright browsers** | **hard fail** | **No** | **Auto-install preflight** |
| **Placeholder credentials** | **silent skip** | **Yes** | **`CHECK_PLACEHOLDER_CREDS`** |

### The #1 Action Item

**The Question Tool (`Argus-Tui/packages/opencode/src/tool/question.ts`) needs an automatic bypass** — either an `ARGUS_AUTO_ANSWER` env var, a `--no-questions` flag, or a default answer config. Without it, any LLM-triggered question deadlocks autonomous mode, and there is no way to predict when the LLM will decide to ask one.

### Secondary Action Items

1. **Remove the `try/catch` around config file loading** (`workflow-runner.ts:542`, `feature-flags.ts:220`). A malformed `argus.config.yaml` should fail hard in autonomous mode, not silently reset to defaults.

2. **Add a global max-assessment-duration circuit breaker** — either an env var `ARGUS_MAX_DURATION_SECONDS` or a config key. Without it, runaway LLM loops or hanging tools can run indefinitely.

3. **Consume `structured` findings from MCP responses** (`executor.ts:502-535`). Currently the executor only checks `result.data` for arrays/strings — the structured findings with proper severity, CWE, and evidence are bypassed.

4. **Add an explicit `ARGUS_AUTO_ANSWER` env var** as a companion to `ARGUS_AUTO_APPROVE`. Even if the question tool isn't bypassed entirely, having a default answer (e.g., `"auto"` or `"yes"`) prevents deadlocks when the LLM asks questions.

5. **Add periodic MCP worker health probes** during assessment. The current reactive restart means tool calls fail before recovery is attempted. A proactive ping every 30s would detect crashes between tool calls.

6. **Fail hard when all phases have zero tools** (`planner.ts:79`). Currently the planner silently skips each phase. If the assessment starts with zero tools, it should fail immediately with a clear message rather than completing with zero findings.
