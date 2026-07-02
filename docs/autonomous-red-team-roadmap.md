# Autonomous Red Team — Implementation Roadmap

**Date:** 2026-07-02
**Scope:** Remaining items from the Autonomous Red Team Readiness Review
**Objective:** Tracked, phased implementation plan for the five remaining architectural workstreams.

---

## Status Summary

| Workstream | Phases | Est. Timeline | Status |
|------------|--------|---------------|--------|
| 1. Dynamic Planning & Exploit Chaining | 3 sub-phases | 4–6 weeks | 🟡 Not started |
| 2. Post-Exploitation & Lateral Movement | 3 sub-phases | 3–4 weeks | 🟡 Not started |
| 3. Browser Verification Pipeline | 4 sub-phases | 3–4 weeks | 🟡 Not started |
| 4. Infrastructure Resilience | 5 sub-phases | 4–5 weeks | 🟡 Not started |
| 5. DB Schema Alignment | 2 sub-phases | 1–2 weeks | 🟡 Not started |

---

## Phase 1: Dynamic Planning & Exploit Chaining (4–6 weeks)

### 1.1 Attack-Graph Traversal Planning

**Problem:** The planner (`planner.ts`) selects YAML workflows by capability. `replan-rules.ts` maps 18 finding subtypes to capabilities via `REPLAN_INSERTABLE`. The Python side has `attack_graph.py` with chain templates, prerequisite/impact maps, and `find_chains()`. `chain_exploit_generator.py` can generate weaponized scripts. None of this is wired into the planner's `replan()` method.

| Step | Files | Description |
|------|-------|-------------|
| 1.1.1 | `planner/planner.ts`, `planner/types.ts` | Add `attackGraph` field to `PlannerContext`. When replan is called, query the Python attack graph via MCP bridge |
| 1.1.2 | `mcp_server.py` | Expose a `get_attack_graph` MCP handler that returns `find_chains()` results and `get_highest_risk_paths()` |
| 1.1.3 | `planner/replan-rules.ts` | Add `REPLAN_CHAINS` map — detected chains trigger new phases (e.g., `sqli_confirmed → POST_EXPLOITATION`) |
| 1.1.4 | `planner/planner.ts` | In `replan()`, if attack chains exist, insert chain-exploitation phases immediately (fix `push` vs `splice` bug) |
| 1.1.5 | `attack_graph.py` | Add `generate_plan_from_graph()` — produces ordered phase list from chain templates |

### 1.2 LLM-Driven Replanning

**Problem:** `mcp_server.py` `_replan()` uses `LLMClient` + `ReActAgent` with session observations. But the TypeScript planner never calls the Python replan during normal execution. No feedback loop from findings to tool selection.

| Step | Files | Description |
|------|-------|-------------|
| 1.2.1 | `workflow-runner.ts` | Wire MCP `handle_agent_init` findings into subsequent phase `handle_agent_next` calls |
| 1.2.2 | `agent/react_agent.py` | Add `plan_next_phase()` method — given all findings, determine next capabilities |
| 1.2.3 | `mcp_server.py` | New `handle_phase_complete` MCP method — receives all phase findings, returns suggested next capabilities |

### 1.3 ExecuteHybrid Workflow YAML Integration

**Problem:** `executeHybrid()` exists in `executor.ts` but no workflow YAML uses `execution: llm_driven`.

| Step | Files | Description |
|------|-------|-------------|
| 1.3.1 | `workflows/*.yaml` | Add `execution: llm_driven` to deep-scan and analyze phases |
| 1.3.2 | `planner/planner.ts` | When `useLLM=true` and phase has `execution: llm_driven`, route through `executeHybrid` |
| 1.3.3 | `executor.ts` | In `executeHybrid()`, feed previous phase findings into `agentInit` context |

---

## Phase 2: Post-Exploitation & Lateral Movement (3–4 weeks)

### 2.1 Credential Extraction & Replay Pipeline

**Problem:** `tasks/post_exploit.py` exists as a Celery task with `run_post_exploit()` that calls `ctx.orchestrator.run_post_exploitation()`. But `run_post_exploitation()` is a stub.

| Step | Files | Description |
|------|-------|-------------|
| 2.1.1 | `orchestrator_pkg/orchestrator.py` | Implement `run_post_exploitation()` — extract credentials from evidence, store in credential store |
| 2.1.2 | `tools/auth_manager.py` | New method `replay_credentials(endpoint, credentials)` — attempt auth with extracted creds |
| 2.1.3 | `tasks/post_exploit.py` | Wire credential replay into the post-exploit task flow |
| 2.1.4 | `engagement/credentials.ts` | Add `storeExtractedCredentials(engagementId, creds)` for cross-session persistence |

### 2.2 Internal Network Probing

**Problem:** No internal probing or pivoting exists.

| Step | Files | Description |
|------|-------|-------------|
| 2.2.1 | `tools/port_scanner.py` | Add `scan_internal_ranges()` — probe adjacent network ranges from foothold |
| 2.2.2 | `tools/attack_surface_mapper.py` | Add `probe_pivot_targets()` — enumerate internal services on responding hosts |
| 2.2.3 | `state_machine.py` | Add `pivot` sub-state to `post_exploitation` with `pivot → scanning` transitions |

### 2.3 Attack Chain Exploitation

**Problem:** `chain_exploit_generator.py` generates LLM scripts but they're never executed.

| Step | Files | Description |
|------|-------|-------------|
| 2.3.1 | `chain_exploit_generator.py` | Add `verify_chain_in_sandbox()` — parse script steps, run in sandbox, report success |
| 2.3.2 | `tasks/post_exploit.py` | Wire chain verification: for each chain, generate script, sandbox-verify, create CONFIRMED finding |

---

## Phase 3: Browser Verification Pipeline (3–4 weeks)

### 3.1 Orchestrated Verification

**Problem:** `workflow-runner.ts` `verifyFindings()` runs verification for HIGH/CRITICAL after each phase. The orchestrator never invokes it. `assessment_orchestrator.py` doesn't call verify.

| Step | Files | Description |
|------|-------|-------------|
| 3.1.1 | `assessment_orchestrator.py` | After each tool execution, if findings exceed severity threshold, call browser verification |
| 3.1.2 | `orchestrator_pkg/orchestrator.py` | Add `run_verification(engagement_id, findings)` — calls `VerificationRunner.run()` via MCP |
| 3.1.3 | `workflow-runner.ts` | Make `verifyFindings()` a configurable pipeline step with threshold from config |

### 3.2 Expanded Verifier Coverage

**Problem:** Only XSS, BOLA/IDOR, and privilege escalation verifiers exist. XSS payload is hardcoded.

| Step | Files | Description |
|------|-------|-------------|
| 3.2.1 | `verifiers/ssrf.ts` | SSRF verifier — probe SSRF endpoints against attacker-controlled listener |
| 3.2.2 | `verifiers/lfi.ts` | LFI verifier — attempt to read `/etc/passwd`, confirm content in response |
| 3.2.3 | `verifiers/jwt.ts` | JWT verifier — swap algorithm to `none`, tamper payload, confirm acceptance |
| 3.2.4 | `verifiers/secrets.ts` | Secret verifier — confirm exposed secrets are still valid |
| 3.2.5 | `verifiers/xss.ts` | Replace hardcoded payload with configurable payload from recon findings |

### 3.3 HAR & Network Evidence Capture

**Problem:** `observer.ts` returns empty response headers. HAR capture off by default. Evidence has empty `packageHash`.

| Step | Files | Description |
|------|-------|-------------|
| 3.3.1 | `browser/engine.ts` | Enable `record_har_path` in Playwright. Store HAR per verification scenario |
| 3.3.2 | `verifiers/*.ts` | Compute actual SHA-256 `packageHash` from stored artifacts |
| 3.3.3 | `evidence/collector.ts` | Persist full request/response objects from HAR into evidence packages |

### 3.4 Authentication Improvements

**Problem:** `login.ts` uses brittle regex-based form detection. OAuth/SAML/MFA fail.

| Step | Files | Description |
|------|-------|-------------|
| 3.4.1 | `browser/login.ts` | Add Playwright locator-based form detection (`getByRole`, `getByLabel`) |
| 3.4.2 | `browser/login.ts` | Detect MFA/CAPTCHA pages, emit `auth_challenge` signal |
| 3.4.3 | `browser/engine.ts` | Add stealth profile — `--disable-blink-features=AutomationControlled`, random UA/locale |

---

## Phase 4: Infrastructure Resilience (4–5 weeks)

### 4.1 Mid-Phase Checkpointing & Inside-Phase Resume

**Problem:** `checkpoint_manager.py` saves checkpoints only after a phase completes. Resume starts from the next phase, not mid-phase.

| Step | Files | Description |
|------|-------|-------------|
| 4.1.1 | `checkpoint_manager.py` | Add `save_tool_checkpoint(engagement_id, phase, tool_name, partial_data)` |
| 4.1.2 | `assessment_orchestrator.py` | Call `save_tool_checkpoint` after each tool execution |
| 4.1.3 | `workflow-runner.ts` | On resume, query checkpoints, skip completed tools |
| 4.1.4 | `bridge/mcp-client.ts` | Add `getCheckpoint(engagementId)` MCP call |

### 4.2 Worker Bridge Degraded Mode

**Problem:** After 3 worker restarts, the bridge throws and halts.

| Step | Files | Description |
|------|-------|-------------|
| 4.2.1 | `bridge/supervisor.ts` | After max restarts, switch to degraded mode instead of throwing |
| 4.2.2 | `bridge/mcp-client.ts` | Add `degradedToolCache` — core tool commands that run without the worker |
| 4.2.3 | `workflow-runner.ts` | On degraded mode, emit warning, queue remaining work for recovery |

### 4.3 Phase Task Idempotency

**Problem:** Phase tasks always attempt work. `run_scan` forces `transition("scanning")` even if already analyzing.

| Step | Files | Description |
|------|-------|-------------|
| 4.3.1 | `tasks/base.py` | Add `check_and_skip_if_terminal(state)` — early return if past this phase |
| 4.3.2 | `tasks/recon.py`, `scan.py`, `analyze.py`, `repo_scan.py` | Add idempotency guard at entry |
| 4.3.3 | `celery_app.py` | Set `acks_late=True`, `reject_on_worker_lost=True` for at-least-once delivery |

### 4.4 WorkflowRunner Cross-Run Serialization

**Problem:** No lock. Two concurrent runs for the same engagement clobber results.

| Step | Files | Description |
|------|-------|-------------|
| 4.4.1 | `workflow-runner.ts` | Acquire distributed lock via bridge before starting phase execution |
| 4.4.2 | `mcp_server.py` | Expose `acquire_engagement_lock` / `release_engagement_lock` MCP handlers |
| 4.4.3 | `engagement/store.ts` | Add optimistic concurrency (`version`/`updated_at`) to root engagement row |

### 4.5 Postgres-Backed DLQ Fallback & Shutdown

**Problem:** DLQ is Redis-only. Shutdown doesn't release locks or flush DLQ.

| Step | Files | Description |
|------|-------|-------------|
| 4.5.1 | `dead_letter_queue.py` | Add Postgres-backed DLQ fallback in `dead_letter_queue` table |
| 4.5.2 | `shutdown_handler.py` | Before force-exit: release all locks, flush pending events to DLQ |
| 4.5.3 | `distributed_lock.py` | Increase default shutdown grace from 30s to 120s |

---

## Phase 5: DB Schema Alignment (1–2 weeks)

### 5.1 Fix Repository vs Migration Mismatches

**Problem:** Several repositories reference columns that don't exist in the shipped migrations. Fresh databases cannot create engagements or save findings.

| Step | Files | Description |
|------|-------|-------------|
| 5.1.1 | `database/migrations/022_add_engagement_columns.sql` | Add `target_url`, `authorization_proof`, `authorized_scope`, `created_by` to `engagements` |
| 5.1.2 | `database/migrations/023_add_finding_columns.sql` | Add `cvss_score`, `owasp_category`, `cwe_id`, `evidence_strength`, `tool_agreement_level`, `fp_likelihood`, `verified`, `last_seen_at` to `findings` |
| 5.1.3 | `database/migrations/024_add_tool_metrics_table.sql` | Create `tool_metrics` table (before `010_add_tool_metrics_engagement.sql`) |
| 5.1.4 | `database/migrations/025_add_target_profiles_table.sql` | Create `target_profiles` with `(org_id, target_domain)` unique constraint |
| 5.1.5 | `database/migrations/026_add_users_table.sql` | Create `users` table referenced by `engagement_repository.py` |
| 5.1.6 | `database/migrations/runner.py` | Verify `run_migrations()` orders correctly and handles idempotent re-runs |

### 5.2 Fix Settings Repository

**Problem:** `settings_repository.py` references `user_email`, `key`, `value` columns but actual table has `user_id` (TEXT UNIQUE) and `settings` (JSONB).

| Step | Files | Description |
|------|-------|-------------|
| 5.2.1 | `database/repositories/settings_repository.py` | Rewrite SQL to query `settings->>'openai_api_key'` etc. from correct schema |
| 5.2.2 | `database/migrations/` | Add migration to create `user_settings` with correct schema |

---

## Priority Order & Dependencies

```
Week 1-2:  DB Schema Alignment (Phase 5)
           → unblocks all repositories that crash on fresh DB

Week 3-4:  Phase Task Idempotency (4.3) + Cross-Run Serialization (4.4)
           → prevents duplicate/corrupted work in multi-worker mode

Week 5-7:  Attack-Graph Planning (1.1) + LLM Replan (1.2)
           → unlocks dynamic, adaptive behavior

Week 8-10: Post-Exploitation Pipeline (Phase 2)
           → depends on 1.1 (chains detected → post-exploit triggered)

Week 11-13: Browser Verification Pipeline (Phase 3) + Degraded Mode (4.2)
           → depends on findings flowing from earlier phases

Week 14-15: Mid-Phase Checkpointing (4.1) + DLQ Fallback (4.5)
           → resilience improvements, lowest dependency
```
