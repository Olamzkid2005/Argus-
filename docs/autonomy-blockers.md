# Autonomy Blockers Analysis — Argus Codebase

> **Date:** 2026-07-18  
> **Scope:** Full analysis of `argus-workers/` Python codebase  
> **Methodology:** Code-reading across all major modules (agent loop, runtime, orchestrator, pipeline, config, LLM client, tasks, dead letter queue, error handling, shadow mode, swarm, governance)  
> **Total blockers identified:** 30

---

## How to Read This Document

Each blocker has:
- **Severity**: 🚫 Fatal / ⚠️ Critical / 🔶 Moderate
- **Location**: Specific file(s) and line numbers where the blocker manifests
- **Evidence**: Direct code quotes showing the problem
- **Why it blocks autonomy**: What specifically prevents self-directed operation

The blockers are ordered by severity, then by logical dependency (upstream blockers first).

---

## 🚫 TIER 1 — FATAL BLOCKERS (3)

These prevent sustained autonomous operation regardless of other fixes.

### 1. No Meta-Cognition Layer

**Location**: `react_agent.py:832` (`_deterministic_plan`), `react_agent.py:1222` (`_fallback_phase_complete`),
`mcp_server.py:SignalQuality`

**Evidence**: The system has zero self-awareness. When the LLM fails, `_deterministic_plan()` iterates
tools sequentially with no adaptation to target characteristics. Signal quality tiers (`CONFIRMED`,
`PROBABLE`, `CANDIDATE`) are defined as **static class constants** in `mcp_server.py` but are never
dynamically adjusted based on actual per-target tool performance.

```python
# react_agent.py:832 — the entire "intelligence" of deterministic fallback:
for tool_name in phase_tools:
    if tool_name not in tried_tools:
        return AgentAction(tool_name, {"target": task}, f"Phase tool: {tool_name}")
```

```python
# react_agent.py:1222-1228 — fallback phase progression returns a degraded signal
# that TypeScript consumes but the Python side never acts on:
def _fallback_phase_complete(phase, findings=None):
    """Fallback phase progression when LLM is unavailable."""
    ...
    return {"fallback": True, ...}  # Signal to TypeScript, not to self
```

**Why it blocks autonomy**: An autonomous system must know when it's operating in degraded mode
and adapt. Argus logs the fallback and moves on, but with no compensatory behavior — no reduced
scope, no different strategy, no "try harder to get the LLM back." It just runs dumber tools.

---

### 2. No Cross-Scan Learning

**Location**: `runtime/memory.py:215` (`_get_long_term`), `feature_flags.py:70` (`MEMORY_RETRIEVAL`),
`orchestrator_pkg/reporting.py` (`TargetProfileService`)

**Evidence**: The `MemoryRetriever` exists and supports 3-tier memory (short/medium/long-term),
but `_get_long_term()` queries `get_by_engagement_id()` — **not** by target URL. This means every
scan of the same target starts from zero.

```python
# runtime/memory.py:215 — looks up by engagement_id, not target URL
profile = repo.get_by_engagement_id(engagement_id)
```

The `MEMORY_RETRIEVAL` feature flag defaults to `False`. When enabled, it only provides context
to the *current* LLM prompt — it doesn't change tool selection strategy or optimize future scans.

`TargetProfileService` stores profiles but only uses them for **report generation context**,
not for strategic optimization of tool ordering.

**Why it blocks autonomy**: A system that cannot learn from experience cannot become more
autonomous over time. Every scan is a groundhog day — same tools, same order, same blind spots.

---

### 3. Shadow Mode Cannot Converge Across Workers

**Location**: `runtime/shadow_mode.py:7-10`

**Evidence**: The shadow comparison system uses `threading.Lock()` which is explicitly documented
as **not cross-process**. In a Celery multi-worker deployment, each worker process has its own
counter. The stated requirement of "100 consecutive successful comparisons before flipping a flag"
can never be reached when different workers are writing to different counters.

```python
# NOTE: threading.Lock() does NOT synchronize across Celery worker processes.
# In multi-worker deployments, these counters are per-process only.
# For cross-process synchronization, use Redis or DB-backed counters.
```

**Why it blocks autonomy**: The shadow mode was designed as the safety mechanism for rolling out
new autonomous features. If it cannot converge, no new feature can be safely promoted from
"feature-flagged off" to "on by default" without manual operator intervention.

---

## ⚠️ TIER 2 — CRITICAL BLOCKERS (8)

These cause silent degradation or failure in common scenarios.

### 4. Hardcoded Cost Caps Kill Autonomy Mid-Scan

**Location**: `config/constants.py:269` (`max_cost_per_engagement: float = 0.50`),
`config/constants.py:346` (`max_cost_usd: float = 0.25`)

**Evidence**: Two separate hard cost caps exist, and they're very low:
- `LLM_MAX_COST_PER_ENGAGEMENT = $0.50` (general LLM features)
- `LLM_AGENT_MAX_COST_USD = $0.25` (agent tool selection)

The `Governance` class has `_DEFAULT_MAX_COST_USD = $10.0` but this only applies when
`GOVERNANCE_V2` feature flag AND `ARGUS_AUTONOMOUS=1` are both enabled. Without those,
the `$0.25` cap from `LLMCostConfig` applies.

For any real-world engagement with 10+ tool selections at ~$0.0002 each, the agent hits the
cost cap after roughly 1,250 LLM calls and silently switches to deterministic-mode tool ordering.
The operator never knows the agent went "dumb."

```python
# config/constants.py:346
max_cost_usd: float = 0.25
```

**Why it blocks autonomy**: An autonomous system that stops reasoning mid-scan and silently
switches to brute-force tool iteration is not autonomous. The cost caps are safety guards
that become execution limiters in practice.

---

### 5. DeterministicRuntime Has Zero Intelligence

**Location**: `runtime/deterministic_runtime.py:35-55`

**Evidence**: When the LLM is unavailable or cost-capped, `DeterministicRuntime` is the fallback.
Its entire logic is:

```python
return execute_scan_pipeline(self.ctx, targets, budget, ...)
```

A direct passthrough to `execute_scan_pipeline` with no adaptation, no target-awareness,
no signal-based tool selection. The pipeline runs tools in a fixed order regardless of
recon findings. A static HTML site gets sqlmap. A WordPress site gets dalfox before wpscan.

**Why it blocks autonomy**: The fallback represents a catastrophic IQ drop — from LLM-driven
reasoning to "for loop over tool list." There's no middle ground, no progressive degradation.

---

### 6. Governance Token Estimates Are Placebo Values

**Location**: `runtime/governance.py:247-262`

**Evidence**: `Governance._estimate_token_usage()` assigns hardcoded per-tool estimates:

```python
estimates = {
    "nuclei": 200,        # Real usage: could be 5,000+ with 100 templates
    "web_scanner": 300,   # Real usage: could be 10,000+ with full scan
    "port_scanner": 100,
    ...
}
return estimates.get(tool_name.lower(), 150)
```

These aren't real token counts. A nuclei scan with 100 templates returning 50 findings
could use 5,000+ tokens in context. The token budget check is a placebo that never fires
when it should.

**Why it blocks autonomy**: A governance system that can't accurately track resources cannot
make informed decisions about when to stop or continue. This creates a security theater
around resource management.

---

### 7. MemoryRetriever Long-Term Memory Is Same-Engagement Only

**Location**: `runtime/memory.py:215`

**Evidence**: Cross-scan learning cannot work because the long-term memory query is scoped
to the current engagement, not the target URL:

```python
# Retrieves profile for the CURRENT engagement only
profile = repo.get_by_engagement_id(engagement_id)
```

A target scanned 5 times has 5 different engagement IDs. The system never retrieves
historical data across engagements for the same target URL.

**Why it blocks autonomy**: The system cannot learn "this tool is noisy on this target type"
or "this target had XSS before — prioritize XSS tools" because it has no cross-scan view.

---

### 8. DLQ Has No Autonomous Replay Strategy

**Location**: `tasks/replay.py:replay_dlq_task`, `dead_letter_queue.py`

**Evidence**: The `DeadLetterQueue` stores failed tasks for later inspection and manual replay.
But there's no automated retry with strategy adaptation:

- DLQ replay re-dispatches the exact same task with the exact same parameters
- No pattern analysis on DLQ entries ("sqlmap keeps failing — maybe the target isn't MySQL")
- No adaptation when 3+ tools fail in sequence

```python
# tasks/replay.py:17 — DLQ replay is a verbatim re-dispatch
def replay_dlq_task(self, task_id: str) -> bool:
    """Find a failed task in the DLQ and re-dispatch it to Celery."""
    ...
    # No strategy modification — same args, same task name
```

**Why it blocks autonomy**: A dead letter queue with only manual replay is a graveyard,
not a recovery mechanism. Autonomous systems must detect failure patterns and adapt.

---

### 9. No Diminishing Returns Detection

**Location**: `react_agent.py:run()`, `runtime/governance.py`

**Evidence**: The agent stops either when it runs out of tools or when
`empty_output_consecutive >= LLM_AGENT_ZERO_FINDING_STOP` (default 4). There is no:

- Finding rate tracking ("findings per tool call" curve)
- Coverage calculation ("what % of attack surface has been tested")
- Diminishing returns model ("last 5 tools found nothing, but first 3 found critical vulns")

```python
# react_agent.py — the only stopping criteria
if empty_output_consecutive >= LLM_AGENT_ZERO_FINDING_STOP and len(tried_tools) >= 4:
    break
```

**Why it blocks autonomy**: The system doesn't know when it's done vs. when it's stuck.
This is the most basic requirement for autonomous task completion — knowing when to stop.

---

### 10. No Graceful Degradation on Partial Tool Failure

**Location**: `react_agent.py:run()`, `orchestrator.py`

**Evidence**: When a tool fails (e.g., nuclei crashes mid-scan):

1. The agent marks it as `tried_tools.add(action.tool)`
2. Moves to the next tool
3. The crashed tool is considered "done" and won't be retried

There is no intermediate strategy — no "try with reduced template set," no "increase timeout
by 2x," no "fall back to alternative tool covering same vulnerability class."

```python
# react_agent.py — tool failure handling
tried_tools.add(action.tool)
results.append(result)
# That's it. No compensatory action.
```

**Why it blocks autonomy**: A single failing tool creates a permanent blind spot in coverage
for the entire engagement. An autonomous system should adapt around failures, not accept them
as final.

---

### 11. Context Window Fragmentation

**Location**: `runtime/engagement_state.py:10` (`OBSERVATION_TRUNCATION_LIMIT = 50`),
`react_agent.py:307` (`get_context`), `config/constants.py:303` (`context_max_tokens = 3500`)

**Evidence**: The agent truncates history to 50 entries, caps each observation at 2000 chars,
and passes only **last 6 observations** to the LLM for tool selection:

```python
# react_agent.py:307
def get_context(self, max_tokens=LLM_AGENT_CONTEXT_MAX_TOKENS):
    recent = self.history[-6:]  # last 6 entries
```

Findings from early tools (e.g., nuclei results showing 50 endpoints) are invisible to the
LLM when making later decisions (e.g., which auth tool to run).

**Why it blocks autonomy**: The LLM makes tool selection decisions with only 6 most-recent
results visible. It cannot reason about the full scan picture or detect patterns across
the entire engagement.

---

### 12. The Feature Flag Dependency Graph Is a DAG of Death

**Location**: `feature_flags.py:70-84` (`AUTONOMOUS_FEATURES`), `orchestrator.py`,
`react_agent.py`

**Evidence**: The autonomous feature flags form a hard dependency chain:

```
ARGUS_AUTONOMOUS=1
  → TRUE_REACT_LOOP (requires ENGAGEMENT_STATE)
  → ENGAGEMENT_STATE (requires CLEAN_ORCHESTRATOR)
  → CLEAN_ORCHESTRATOR (requires EXECUTION_ENGINE)
  → GOVERNANCE_V2
  → MEMORY_RETRIEVAL
  → FEEDBACK_LOOP
  → HYPOTHESIS_ENGINE
  → ATTACK_GRAPH_V2
```

If ANY flag in the chain is off, downstream features silently degrade. But the startup log
just says "14 autonomous features activated" — no indication of which are truly functional
or which dependencies are missing.

```python
# feature_flags.py:237 — misleading log message
logger.info("Feature flags: ARGUS_AUTONOMOUS is enabled — %d autonomous features activated",
            len(AUTONOMOUS_FEATURES))
```

**Why it blocks autonomy**: An operator enabling `ARGUS_AUTONOMOUS=1` gets a false sense
of capability. Many features are only partially implemented or silently gated behind
unmet dependencies.

---

### 13. Celery Task Re-entrancy Is Fragile

**Location**: `tasks/recon.py:82`, `tasks/analyze.py:67`, `tasks/scan.py`

**Evidence**: Tasks check for duplicate execution via Redis keys but only detect
full-duplicate (same task ID), not partial re-execution:

```python
# tasks/recon.py:82 — only checks for exact duplicate
# (e.g. Celery retry delivered duplicate task), skip immediately.
```

If a scan phase already saved 5 findings and the worker crashes, the retry starts from
scratch and creates duplicate findings. The `snapshot_manager.py` uses SERIALIZABLE
isolation level and retries on serialization failures, but the orchestrator phases
are not wrapped in a single serializable transaction.

**Why it blocks autonomy**: Partial re-execution leading to duplicate data means the
system's outputs are not deterministic. An autonomous system needs reliable
exactly-once semantics for its findings.

---

## 🔶 TIER 3 — MODERATE BLOCKERS (17)

These create gaps that compound in edge cases or long-running engagements.

### 14. Error Classification Import Is Silently Broken

**Location**: `exceptions.py:27-31`

**Evidence**: `ArgusError.__init__` tries to call `tag_error()` but silently swallows
import failures:

```python
try:
    from error_classifier import tag_error
    tag_error(self, self.error_code)
except ImportError:
    pass  # Silently swallows — ErrorCode never tagged
```

When this import fails, `classify_error()` falls back to unreliable string-pattern
matching instead of deterministic code-based classification.

---

### 15. Pipeline Router Retry Has No Strategy Change

**Location**: `pipeline_router.py:84-101`

**Evidence**: When retrying a transient pipeline failure, it retries the identical
operation with the same parameters — just with exponential backoff:

```python
for attempt in range(_MAX_RETRIES + 1):
    try:
        return execute_recon_tools(ctx, target, budget, ...)
    except Exception as e:
        if _is_transient_error(e):
            time.sleep(backoff)
            # Retries IDENTICAL operation — no strategy change
```

There's no fallback to simpler tools, reduced aggressiveness, or different approach.

---

### 16. Attack Graph Is Static, Not Adaptive

**Location**: `attack_graph.py`, `attack_graph_db.py`, `orchestrator.py:run_analysis`

**Evidence**: The attack graph is built from findings **after scanning completes**.
It never influences tool selection during the scan, never prioritizes remaining tools
based on emerging attack chains, and is purely a reporting artifact.

```python
# orchestrator.py: — attack graph is build in analysis phase, not during scanning
# (attack graph generation happens after all scanning is done)
```

---

### 17. No A/B Testing of Scanning Strategies

**Location**: `runtime/shadow_mode.py`

**Evidence**: Shadow mode exists for code refactoring verification (comparing new code
vs old code outputs), but there is no operational A/B testing — no ability to run
two different scanning strategies in parallel and compare effectiveness.

---

### 18. Swarm Agents Don't Share Learnings

**Location**: `agent/swarm.py` (`SpecialistAgent.__init__`)

**Evidence**: The `SwarmOrchestrator` deep-copies recon context for each specialist agent
(IDORAgent, AuthAgent, APIAgent). While this prevents shared mutable state, it also prevents:

- Cross-agent learning (if IDORAgent finds an auth bypass, AuthAgent doesn't know)
- Intelligent prioritization (agents run in fixed order, not by likelihood of findings)
- Confidence merging (findings from different agents aren't cross-referenced)

```python
# agent/swarm.py — each agent gets an isolated copy
self.recon_context = copy.deepcopy(recon_context) if recon_context else None
```

---

### 19. MCP Bridge Fallback Removes Safety Controls

**Location**: `orchestrator.py:128-148`

**Evidence**: When `MCPToolBridge` fails to initialize, the orchestrator falls back to
registering tools **without sandboxing, circuit breakers, or metrics**:

```python
except Exception as e:
    self.mcp_bridge = None
    for tool in build_mcp_tool_definitions():
        self.mcp.register_tool(tool)  # Direct registration — no sandboxing
```

---

### 20. Auth Checkpoint Has No Re-authentication Cycle

**Location**: `agent/auth_checkpoint.py`, `react_agent.py:1250-1312`

**Evidence**: On Celery retry, the auth checkpoint is loaded but:
- Doesn't verify credentials are still valid before use
- Doesn't attempt re-registration if login fails
- If the session is expired, the agent silently continues without auth
- No "credentials expired → re-authenticate → retry" loop

---

### 21. Bug Bounty Knowledge Files May Not Exist

**Location**: `agent/agent_prompts.py:_load_bugbounty_context`

**Evidence**: The `_load_bugbounty_context()` function tries to load `.md` methodology
files from `agent/bugbounty_knowledge/vulnerabilities/`:

```python
ref_file = kb_root / "vulnerabilities" / f"{vuln_class}.md"
if ref_file.exists():
    content = ref_file.read_text(encoding="utf-8")
```

If these files don't exist (fresh checkout, new deployment), the bug bounty mode
silently falls back to empty methodology context. The LLM gets no Bug-Reaper
methodology and operates blind.

---

### 22. Git Host Allowlist Blocks Private Git Hosts

**Location**: `config/constants.py:185-200`

**Evidence**: The `GitSSRFConfig` has a hardcoded allowlist of 13 public git hosts.
Private self-hosted GitLab/GitHub Enterprise instances are blocked by default.
While configurable via `ARGUS_ALLOWED_GIT_HOSTS` or `argus.config.yaml`, this requires
manual operator action — an autonomous system cannot adapt to unlisted hosts.

---

### 23. Orbited Lock Release on Shutdown Is Best-Effort

**Location**: `shutdown_handler.py:171-190`

**Evidence**: The `GracefulShutdownHandler` tries to release distributed locks and flush
DLQ entries during shutdown, but all operations are wrapped in `try/except` with `pass`:

```python
try:
    lock.release(eng_id)
except Exception as lock_err:
    logger.warning("Failed to release lock %s on shutdown: %s", eng_id, lock_err)
```

---

### 24. No Cross-Provider LLM Fallback

**Location**: `llm_client.py`

**Evidence**: The `LLMClient` supports auto-detection of OpenAI, OpenRouter, Gemini,
and Anthropic providers — but only one at a time. There's no fallback chain:
"try OpenAI → if unavailable, try Anthropic → if unavailable, try local model."
When the single configured provider is down, the entire system degrades.

---

### 25. No Streaming / Partial Results for Long-Running Tools

**Location**: `streaming.py`, `tool_core/result.py`

**Evidence**: Tool results are collected as complete outputs before being fed back
to the agent. There's no partial-result streaming — if nuclei takes 5 minutes on
500 targets, the agent sits idle for the entire duration before learning any results.

---

### 26. Auth Token Rotation Is Not Handled

**Location**: `agent/auth_context.py`, `tools/auth_manager.py`

**Evidence**: The system captures session tokens/cookies during authentication but has
no mechanism for detecting token expiration mid-scan or rotating expired tokens.
A session that expires during a 30-minute scan causes all subsequent tools to fail
silently.

---

### 27. LLM Prompt Sanitization May Over-Redact

**Location**: `agent/agent_prompts.py:_sanitize_for_llm`

**Evidence**: The `_sanitize_for_llm()` function truncates all external data to 3000 chars.
This means long tool outputs (nuclei with 200 findings, full scan results) are aggressively
truncated before reaching the LLM. The first 3000 chars may be headers/metadata while the
actual findings are in the truncated portion.

---

### 28. No Session Stickiness for Multi-Phase Workflows

**Location**: `celery_app.py`, `tasks/`

**Evidence**: Celery tasks for different phases of the same engagement (recon → scan → analyze)
may run on different workers. While the state machine and checkpoints handle this, there's
no worker affinity — causing unnecessary Redis/DB round-trips to re-sync state on every phase
transition.

---

### 29. No Observability of Degradation State

**Location**: `health_server.py`, `health_monitor.py`

**Evidence**: The health endpoint (`GET /health`) reports `status: "healthy" | "degraded" | "down"`
but the degraded determination is based on system resources (memory, CPU) and tool availability,
not on the agent's cognitive state. There's no metric for "LLM fallback rate" or
"deterministic mode percentage" — operators can't tell if the agent is operating in degraded
mode from the health checks alone.

---

### 30. No Operator Feedback Loop for Scan Results

**Location**: `models/feedback.py`

**Evidence**: The `Feedback` model exists (feature-flagged as `FEEDBACK_LOOP`, default `False`)
but has no integration with any actual feedback collection mechanism. There's no endpoint
for operators to mark findings as true/false positives, no UI for scan quality ratings,
and no mechanism for operator feedback to influence future scan strategy.

```python
# models/feedback.py:62
if not _ff_enabled("FEEDBACK_LOOP"):
    logger.debug("Feedback loop disabled (set ARGUS_FF_FEEDBACK_LOOP=1)")
```

---

## Summary: The Three Hardest Problems

| Rank | Problem | Why It's Hard |
|------|---------|---------------|
| 🥇 | **No meta-cognition** | The system can't distinguish "I found nothing because the target is clean" from "I found nothing because my LLM is down." Requires confidence calibration, uncertainty estimation, and self-diagnosis — open AI/ML research problems. |
| 🥈 | **No cross-scan learning** | Every scan starts from zero. Target profiles exist but aren't used to improve strategy. Requires persistent state management across engagements, learning from past outcomes, and adaptive strategy evolution — a data engineering + ML problem. |
| 🥉 | **Feature flag dependency tangle** | 14+ interdependent autonomy features, half partially implemented, all gated behind flags. The flags were meant for gradual rollout but became a permanent dependency graph where disabling one flag breaks downstream features silently. A software architecture problem. |

## Quick Reference by File

| File | Critical Blockers |
|------|-------------------|
| `react_agent.py` | #1 (meta-cognition), #9 (diminishing returns), #10 (partial failure), #11 (context fragmentation) |
| `runtime/shadow_mode.py` | #3 (per-process counters cannot converge) |
| `runtime/memory.py` | #2 (same-engagement memory), #7 (no cross-scan learning) |
| `runtime/governance.py` | #6 (placebo token estimates) |
| `runtime/deterministic_runtime.py` | #5 (zero-intelligence fallback) |
| `config/constants.py` | #4 (cost caps kill mid-scan) |
| `feature_flags.py` | #12 (DAG of death) |
| `dead_letter_queue.py` / `tasks/replay.py` | #8 (no autonomous replay) |
| `exceptions.py` | #14 (broken ErrorCode import) |
| `orchestrator.py` | #19 (MCP bridge fallback unsafe) |
| `agent/swarm.py` | #18 (no cross-agent learning) |
| `agent/auth_checkpoint.py` | #20 (no re-auth cycle) |
| `agent/agent_prompts.py` | #21 (missing knowledge files), #27 (over-redaction) |
| `attack_graph.py` | #16 (static, not adaptive) |
| `pipeline_router.py` | #15 (retry no strategy change) |
| `llm_client.py` | #24 (no cross-provider fallback) |
