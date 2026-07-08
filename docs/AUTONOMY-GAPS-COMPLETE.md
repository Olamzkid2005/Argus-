# Argus: Red Team Autonomy Gaps — Complete Audit

All file paths and line numbers verified against the actual codebase.
Not based on roadmap documents — based on reading the source code.

---

## Table of Contents
- [1. Browser Verification Pipeline](#1-browser-verification-pipeline-not-self-executing)
- [2. Browser Authentication Pipeline — 7 Gaps](#2-browser-authentication-pipeline--7-gaps)
- [3. Exploit Chain Loop (Dynamic Pipeline Insertion)](#3-exploit-chain-loop-dynamic-pipeline-insertion)
- [4. Tool Definition Silent Failures](#4-tool-definition-silent-failures)
- [5. Assessment Pipeline Never Closes the Loop](#5-assessment-pipeline-never-closes-the-loop)
- [6. Database Schema / Runtime Mismatches](#6-database-schema--runtime-mismatches)
- [7. Additional Critical Gaps](#7-additional-critical-gaps)
- [8. Configuration & Infrastructure Dependencies](#8-configuration--infrastructure-dependencies)
- [9. LLM Client & Agent Loop Gaps](#9-llm-client--agent-loop-gaps)
- [10. Event Streaming & WebSocket Gaps](#10-event-streaming--websocket-gaps)
- [11. Task & Worker Infrastructure Gaps](#11-task--worker-infrastructure-gaps)
- [12. Reporting & Compliance Gaps](#12-reporting--compliance-gaps)
- [13. Scope Validation & Security Gaps](#13-scope-validation--security-gaps)
- [Build Order Priority Summary](#build-order-priority-summary)

---

## 1. Browser Verification Pipeline (Not Self-Executing)

### 1.1 `run_verification()` Marks Findings But Never Launches Playwright

**File:** `argus-workers/orchestrator_pkg/orchestrator.py`, lines 1074–1134

`run_verification()` iterates over findings and sets `_needs_browser_verification = True`, then emits a WebSocket event. It never actually calls the Playwright-based verifier functions (BOLA, XSS, PrivEsc, SSRF, LFI, JWT, Secrets).

The side method `_maybe_run_browser_scanner()` (line ~1214) only runs a generic browser scanner for SPA tech detection — not the actual verifiers.

**What to build:** After scan tools complete, for each finding with severity ≥ HIGH/CRITICAL, route to the matching Playwright verifier via MCP. Then call `ConfidenceEngine.promote()` to upgrade `HIGH → VERIFIED → CONFIRMED` when verification passes.

### 1.2 Manual-Only CLI Verification

**File:** `Argus-Tui/packages/opencode/src/argus/commands/verify.ts`

Verification is exposed only as a manual CLI command (`argus verify <finding-id>`). The `workflow-runner.ts` never automatically triggers `verifyFindings()` after a phase completes.

**What to build:** Wire `workflow-runner.ts` to subscribe to the `VERIFICATION_RECOMMENDED` WebSocket event from the Python orchestrator and automatically dispatch verification.

### 1.3 Evidence Integrity Check Uses Empty Hashes

**File:** `argus-workers/orchestrator_pkg/orchestrator.py`, lines 1174–1195

Evidence collection computes SHA-256 hashes, stores them, then verifies them — but the hash values are computed on the response body only (not the full evidence context), and there's no integrity check cross-referencing the captured screenshot/HAR/request against the hash.

### 1.4 Browser Verification Not Wired into ConfidenceEngine

**File:** `Argus-Tui/packages/opencode/src/argus/engagement/confidence.ts`

The `ConfidenceEngine.promote()` method has paths to promote findings from `HIGH → VERIFIED → CONFIRMED` when browser verification passes, but it is never called because verification never happens automatically.

---

## 2. Browser Authentication Pipeline — 7 Gaps

**File:** `Argus-Tui/packages/opencode/src/argus/browser/login.ts`

### 2.1 "Auth Success" Defined by Absence, Not Presence (Line 335)

`detectAuthSuccess()` (line 335) returns `true` unless the page body matches one of a handful of MFA/CAPTCHA/error-message regexes. There's no positive check — no lookup for a logout button, an authenticated-only element, a changed session cookie, or a successful authenticated API call.

Combined with the URL check (`stillOnLogin`, line 319 — only matches `/login`, `/signin`, `/auth` in the path), this means: any login attempt that doesn't redirect to one of those three path patterns *and* doesn't happen to contain one of the exact English keywords ("invalid credentials," "login failed," etc.) is silently counted as a successful login — even if nothing actually happened.

**Fix:** Replace with positive confirmation:
1. Check for an authenticated-only DOM element (logout button, user avatar, profile link)
2. Check session cookies changed (read `page.context().cookies()` before/after)
3. Probe an authenticated-only endpoint (`/api/me`, `/profile`) for 200 vs 401/403
4. Only fall back to `return true` if ALL three checks are inconclusive

### 2.2 Verifiers Proceed When Login Is Known to Have Failed (Line 181)

**File:** `bola.ts`, line 181–188

When `loginIfFormPresent()` returns `false`, the code doesn't abort — it logs `"Login may have failed for {user} — proceeding with resource check"` and continues.

Then `accessible = page.url() === resourceUrl || !isAccessDenied(body)` (further down) treats anything short of an explicit 401/403/"forbidden"/"access denied" string as accessible. A failed login that lands on a generic redirect or a blank error page gets scored as successful unauthorized access.

**Fix:** Change `bola.ts:188`, `priv-esc.ts:97`, and any other verifier to return `false` (fail closed) when login returns `false`.

### 2.3 Credential/Token Injection Has No Verification (Lines 40–73)

`injectAuthCookies()` and `injectLocalStorageTokens()` (lines 40–73) set cookies/localStorage and return `void`. No check that the target actually accepted them. No follow-up navigation-and-verify call.

**Fix:** After injection, navigate to the target URL and confirm the session works using `detectAuthSuccess()` (the fixed version from 2.1).

### 2.4 Cookie Injection Defaults `secure: true` Regardless of Target Protocol (Line 51)

`injectAuthCookies` (line 51) defaults `secure: true` on every injected cookie unless the caller overrides it. If the target is being tested over plain HTTP (internal/staging pentest scope), the browser silently refuses to send `secure` cookies, and the injected session never attaches to requests.

**Fix:** Accept the target URL as a parameter and set `secure: url.startswith("https://")`.

### 2.5 No Support for Multi-Step Login Flows

The code assumes username and password fields are on the same page/form. Modern flows that ask for the identifier first and only render the password field after a submit (common even outside true OAuth/SSO) aren't handled — `loginWithLocators` and the CSS fallback both look for password-field presence up front.

**Fix:** In `loginWithLocators`, if `input[type=password]` isn't found but a submit button is present near the email field, click it, wait for navigation, then look for the password field on the next page.

### 2.6 OAuth/SSO Detection Is a Dead End (Line 236)

When `hasOAuth` is detected (line 236), the function returns `false` and emits a challenge — but nothing automatically falls through to `injectAuthCookies`/`injectLocalStorageTokens` as the comments suggest should happen. Checking `bola.ts`, `xss.ts`, and `priv-esc.ts`, none of them wire that fallback in.

**Fix:** Add a new top-level function `authenticateSession()` that:
1. Tries `loginIfFormPresent()` first
2. If OAuth is detected, falls through to token/session injection using credentials from `CredentialStore`
3. Verifies the session works after injection

Then update all verifiers to call `authenticateSession()` instead of `loginIfFormPresent()`.

### 2.7 No Backoff Between Login Attempts

`loginIfFormPresent` submits and checks immediately with no delay logic. If a verifier retries against different credential sets (which `bola.ts`'s `checkAccess` loop structure suggests it does), nothing prevents tripping a target's account-lockout or WAF rate limit.

**Fix:** Add a `loginDelayMs` parameter (default 2000ms) between login attempts. Track attempts in an internal counter; if login fails after 3 tries, emit an `auth_error` challenge and abort.

---
## 9. LLM Client & Agent Loop Gaps

**File:** `argus-workers/llm_client.py`, `argus-workers/agent/react_agent.py`

### 9.1 Massive Code Duplication in `chat()` / `chat_sync()` / `chat_async()`

`LLMClient` has three near-identical ~200-line methods (`chat()`, `chat_sync()`, `chat_async()`) that each implement the same retry loop, circuit breaker, rate limiting, and response parsing logic. Each has its own copy of the OpenAI SDK path AND the generic HTTP API path. A bug fix in `chat_sync()` is routinely missed in `chat_async()`, and vice versa.

**Lines:** `chat()` starts at line ~195, `chat_sync()` at ~340, `chat_async()` at ~520

**Fix:** Extract a shared `_call_llm()` method that both async and sync wrappers delegate to. Use a `SyncClient`/`AsyncClient` strategy pattern rather than if/else branching.

### 9.2 Circuit Breaker Never Opens With Default Settings

`_circuit_threshold = 5` but `max_retries = 2`. The circuit breaker requires 5 consecutive failures to open, but the retry loop gives up after 2+1=3 attempts. The circuit breaker is functionally dead with default settings — it can never trigger because the retry loop exits before reaching 5 failures.

**Lines:** `llm_client.py:133-134`, `llm_client.py:45`

**Fix:** Set `_circuit_threshold` to `max_retries + 1` (i.e., 3) so the circuit opens when all retries are exhausted. Or increase `max_retries` to match the threshold.

### 9.3 Redis Rate Limiter Creates New Connection Per Call

Both `_check_rate_limit()` and `_check_rate_limit_async()` call `redis.from_url()` to create a new Redis connection on every invocation. No connection pooling, no reuse. This adds ~5ms per LLM call just for TCP handshake.

**Lines:** `llm_client.py:161-162`, `llm_client.py:216-217`

**Fix:** Initialize the Redis client once in `__init__()` and reuse it. Or use a connection pool.

### 9.4 Generic HTTP API Calls in `chat()` Have No Timeout

The OpenAI SDK path uses `asyncio.wait_for(..., timeout=30)`, but the generic HTTP API path (`chat()` method, line ~280) uses `httpx.AsyncClient(timeout=30)` — correct. However, `chat()` passes `timeout=30` to `httpx.AsyncClient` constructor, NOT to `client.post()`. If the server hangs indefinitely, the client waits forever (TCP keepalive can take 2+ hours).

**Fix:** Pass `timeout=httpx.Timeout(30.0)` to both the client constructor AND the `client.post()` call, or set the timeout explicitly on each request.

### 9.5 Anthropic Keys Detected But Silently Misconfigured

`sk-ant-` prefixed keys are detected at line ~93 but explicitly NOT auto-configured because "Anthropic's API is not OpenAI-compatible." The code still falls through to OpenAI request format. An Anthropic key will send an OpenAI-formatted payload to an Anthropic endpoint (if `LLM_API_URL` is set) or to the default OpenAI URL, failing with a confusing auth error.

**Lines:** `llm_client.py:93-98`

**Fix:** Either auto-detect Anthropic and switch to the correct payload format, or raise a clear error at init time telling the user to set `LLM_PROVIDER` and `LLM_API_URL` explicitly.

### 9.6 LLM Tool Selection Failures Are Silent

`_call_llm_for_action()` catches ALL exceptions and returns `None`. The caller in `plan_next_action()` silently falls back to the deterministic plan. There's no metric, no alert, no indication in the report that the LLM failed and the agent ran in degraded mode.

**Lines:** `react_agent.py:720-730`

**Fix:** Log a warning with the exception type and count of previous LLM failures. Emit an `ERROR_HINT` event to notify the UI that the agent is running in degraded mode.

### 9.7 `deterministic_plan()` Matches Phase Names by Substring

`_deterministic_plan()` does `if phase_name in task.lower()` — if the task description contains the phase name as a substring, it matches. A task like "docker-scan-tool: example.com" would match the `scan` phase tools. This is fragile and can produce wrong tool selections.

**Lines:** `react_agent.py:737-741`

**Fix:** Use exact prefix matching (`task.lower().startswith(phase_name + ":")` or similar).

### 9.8 Auth Checkpoint Restore Runs in Background Thread With Silent Timeout

When restoring an auth session from checkpoint on agent start, the code uses `ThreadPoolExecutor` with a 30s timeout. If the login takes longer than 30s (slow network, rate limiting), a `TimeoutError` is caught and logged, and the agent proceeds **without authentication**. No challenge is emitted to the UI.

**Lines:** `react_agent.py:1045-1080`

**Fix:** Emit an `auth_error` challenge when checkpoint restore times out. Allow the user to re-enter credentials or skip auth explicitly.

---
## 10. Event Streaming & WebSocket Gaps

**Files:** `argus-workers/streaming.py`, `argus-workers/websocket_events.py`

### 10.1 Dual Event System: SSE and Redis WebSocket (Dead Code Path)

There are TWO event publishing systems:
- `StreamManager` (in-process SSE via `streaming.py`)
- `WebSocketEventPublisher` (Redis pub/sub via `websocket_events.py`)

Comments throughout `streaming.py` say "WebSocket publishing removed (M-07 consolidation)" but `websocket_events.py` still has a complete, active, and tested implementation with all methods, batching, and persistence logic. The M-07 consolidation is incomplete.

**Fix:** Either delete `websocket_events.py` and all references, or finish the consolidation by removing the SSE path and relying solely on Redis pub/sub. Not both.

### 10.2 `StreamManager.publish()` Silently Drops Events on Full Queues

When a subscriber queue hits its 1000-item limit, `publish()` calls `q.put_nowait(event)` which raises `queue.Full`. This is caught and logged, but the event is silently dropped. Critical findings can be lost in real-time if the UI is slow to consume.

**Lines:** `streaming.py:167-180`

**Fix:** Log the dropped event with its type and engagement_id so operators can detect missed events. Consider a TTL-based backpressure strategy (block for up to 100ms, then drop oldest) instead of immediate drop.

### 10.3 `emit_*()` Functions Duplicate Event Construction

`emit_thinking()`, `emit_tool_start()`, `emit_finding()`, etc. each construct their own Event object inline. The transactional emitter path (`_maybe_transactional()`) ALSO reconstructs the same data from the same dict. Every new event type requires copying the construction logic into two places.

**Lines:** `streaming.py:390-580`

**Fix:** Add an `emit_event()` helper that takes a type and data dict, and have all `emit_*()` functions delegate to it. The transactional emitter should also use the same helper.

### 10.4 `WebSocketEventPublisher._persist_scanner_activity()` Opens Raw DB Connection Every Call

`_persist_scanner_activity()` calls `from database.connection import get_db` and opens a raw DB connection on every invocation. This is called potentially hundreds of times per engagement (once per scanner activity event). No connection pooling is used.

**Lines:** `websocket_events.py:565-580`

**Fix:** Use the shared DB connection pool or batch persistence writes.

---
## 11. Task & Worker Infrastructure Gaps

**Files:** `argus-workers/celery_app.py`, `argus-workers/tasks/*.py`

### 11.1 Database Migrations Run at Module Import Time

`run_migrations()` in `celery_app.py` line 76 is called as a module-level statement. If a migration fails (e.g., syntax error in SQL, missing table), the entire Celery worker crashes at import time. There's no graceful degradation or retry.

**Lines:** `celery_app.py:76`

**Fix:** Move `run_migrations()` to a lazy init function that runs on the first task execution, with retry logic and proper error reporting.

### 11.2 No Migration Rollback Strategy

Migrations are applied in sorted SQL file order with no transaction wrapping. If migration `005_add_column.sql` fails halfway, the changes from `001-004` are already committed. The database is left in an inconsistent state with no mechanism to roll back.

**Lines:** `celery_app.py:76`, `database/migrations/runner.py`

**Fix:** Wrap all migrations in a single transaction, or add version tracking that supports rollback.

### 11.3 Scheduled Email Reports Are Never Actually Sent

`_send_report_email()` in `tasks/report.py` is a literal no-op that logs "Email sending not configured — _send_report_email is a placeholder" at WARNING level. Scheduled reports are generated and stored but the email delivery step is completely missing.

**Lines:** `tasks/report.py:295-305`

**Fix:** Integrate with SendGrid, AWS SES, or Resend. Or at minimum, generate a downloadable link and log it instead of the current no-op.

### 11.4 Celery Worker Concurrency vs. Task Duration Mismatch

`worker_concurrency=8` with `worker_prefetch_multiplier=1` means only 8 tasks run simultaneously. Each scan/recon task takes 30-60+ minutes. With 8 concurrent slots and 30-minute tasks, the system can process at most 16 engagements per hour — a significant bottleneck for an automated red team tool.

**Lines:** `celery_app.py:106-108`

**Fix:** Increase `worker_concurrency` proportional to available CPU/memory, or use task-specific `soft_time_limit` values that match actual tool runtime (nuclei can take 20+ minutes per target).

### 11.5 Report Generation Opens Raw DB Connections Without Pooling

`get_findings_summary()`, `generate_compliance_report()`, and `generate_full_report()` all call `connect(db_conn_string)` to open a new PostgreSQL connection, and `conn.close()` in the finally block. They bypass the connection pool used by every other component.

**Lines:** `tasks/report.py:100-105`, `tasks/report.py:315-320`, `tasks/report.py:440-445`

**Fix:** Use `db_cursor()` from `database.connection` (the connection pool) instead of opening raw connections.

---
## 12. Reporting & Compliance Gaps

**Files:** `argus-workers/tasks/report.py`, `argus-workers/compliance_reporting.py`

### 12.1 Jinja2 Template Rendering May Use Nonexistent Template

`generate_full_report()` calls `generator.env.get_template("full_report.html")` on a `ComplianceReportGenerator` instance. If the generator doesn't have an `env` attribute (it might use string-based templates or a different renderer), this will crash with `AttributeError`.

**Lines:** `tasks/report.py:540-542`

**Fix:** Verify the template path and `env` attribute exist, or add a fallback template renderer.

### 12.2 SBOM Generation Always Runs Regardless of Finding Types

`generate_full_report()` always calls `generate_sbom_from_findings()`, even when there are no dependency/SBOM findings. This wastes CPU time and may produce empty/invalid SBOMs that get persisted to the database.

**Lines:** `tasks/report.py:496-508`

**Fix:** Only generate SBOM when dependency findings are present.

---
## 13. Scope Validation & Security Gaps

**Files:** `argus-workers/tools/scope_validator.py`, `argus-workers/orchestrator_pkg/scan.py`

### 13.1 Duplicate Scope Logic in Multiple Places

`scope_validator.py` has `validate_scope()` which returns `True` when `authorized_scope is None`. `scan.py` has `_is_reachable()` with its own private IP/loopback blocking. The ReAct agent has `_validate_arguments()` with ANOTHER copy of the IP blocking logic. These three implementations are independently maintained and frequently out of sync.

**Lines:** `scope_validator.py:45-55`, `scan.py:80-130`, `react_agent.py:785-830`

**Fix:** Consolidate all scope/destination validation into a single `ScopeValidator` class with a single entry point. The ReAct agent, scan pipeline, and scope validator should all use the same method.

### 13.2 Scope Validation Allows All When `authorized_scope` Is None

(Already documented in Gaps 7.7. Keeping for completeness.)

**Fix:** When `authorized_scope` is not configured, emit a loud warning and require explicit `--allow-unscoped` flag to proceed.

### 13.3 Pipeline Router Is a No-Op Pass-Through

`pipeline_router.py` is 80 lines of imports and wrappers with zero error handling, zero retry logic, and zero routing. It just calls `orchestrator_pkg.recon.execute_recon_tools()` and `orchestrator_pkg.scan.execute_scan_tools()`. Despite the name, there's no routing logic, no alternate method (AMP) support, and no fallback.

**Lines:** `pipeline_router.py:1-80`

**Fix:** Remove `pipeline_router.py` and have callers import from `orchestrator_pkg` directly. Or implement actual routing logic with AMP support.

### 13.4 AUTH_CHECKPOINT_KEY Warnings at Startup But Not Enforced

`celery_app.py` emits a `logger.warning()` when `AUTH_CHECKPOINT_KEY` is not set, but the application continues to run. Workers can process auth-dependent tasks without encryption keys, silently creating unencrypted auth checkpoints.

**Lines:** `celery_app.py:53-66`

**Fix:** Make `AUTH_CHECKPOINT_KEY` mandatory when the `auth_checkpoint` feature is enabled. Crash at startup with a clear error message instead of silently allowing unencrypted checkpoints.

---
## 3. Exploit Chain Loop (Dynamic Pipeline Insertion)

### 3.1 Attack Graph Detects Chains, Pipeline Ignores Them

**File:** `argus-workers/attack_graph.py`, lines ~200–450

The attack graph has **8 chain rules** that successfully detect chains like SQLi → data exfiltration, SSRF → cloud metadata → AWS compromise, XSS + CSRF → ATO, etc. `generate_plan_from_graph()` produces exploitation phase plans. But nowhere does the orchestrator dynamically inject an exploitation phase mid-pipeline.

### 3.2 ReAct Agent `plan_next_phase()` Runs But Pipeline Doesn't Consume It

**File:** `argus-workers/agent/react_agent.py`, line 730

The orchestrator runs all phases in linear order without checking if replanning is needed between phases. `handle_phase_complete()` exists and analyzes findings, but the assessment pipeline doesn't call it between phases to decide "should I insert an exploitation phase before reporting?"

### 3.3 MCP `_replan()` Is Functional But Feedback Loop Is Broken

**File:** `argus-workers/mcp_server.py`, line ~985

The `_replan()` method creates an `LLMClient`, builds session context, and calls `ReActAgent.plan_next_action()`. When the LLM decides to continue, it returns new tool calls. But the orchestrator never checks `_replan()` output between phases.

### 3.4 TypeScript Planner Only Maps 8 Subtypes, Can't Insert Multi-Step Workflows

**File:** `Argus-Tui/packages/opencode/src/argus/planner/planner.ts`

**Fix:** Add a replan checkpoint between every phase in the orchestrator. After `recon` completes, check findings, query the attack graph, and decide if an exploitation phase should be injected before `scan`.

---
## 4. Tool Definition Silent Failures

### 4.1 Playwright YAML Spec Doesn't Match Python Script

**Files:** `Argus-Tui/packages/opencode/src/argus/tools/definitions/playwright-xss.yaml`, `argus-workers/tools/scripts/playwright_xss.py`

The YAML declares the script path as `tools/scripts/playwright_xss.py`, but the MCP server can't find it because the path resolution doesn't account for the Python worker's container filesystem.

### 4.2 Critical Missing Binaries Silently Skipped

**File:** `argus-workers/mcp_server.py`, lines 312–398

If nuclei, nmap, sqlmap, subfinder, httpx, or whatweb are missing, the tool is silently marked as invalid and skipped. No degraded-mode logging, no "recommended tools missing" warning in the report, and no fallback using alternative tools.

**Fix:** Add a pre-flight check that warns the operator at startup which tools are missing. Add an `--enforce-tools` flag that aborts if critical tools are unavailable.

### 4.3 `FINDINGS_EXIT_CODES` Missing Critical Tools

**File:** `argus-workers/tool_core/sandbox.py`, line 55
**File:** `argus-workers/mcp_server.py`, line 468

The dict mapping tool names to findings-bearing exit codes is missing `nuclei` and `dependency_check`. When these tools find vulnerabilities and exit with their standard code, the sandbox treats it as a crash/error rather than a successful finding.

### 4.4 Tool Cache Returns Stale Results on Phase Rerun

**File:** `argus-workers/tools/tool_cache.py`

The tool cache uses a simple TTL-based expiration. When a phase is rerun (e.g., after the user provides additional credentials), the cache returns stale results from the previous run.

---
## 5. Assessment Pipeline Never Closes the Loop

### 5.1 Post-Exploitation Exists But Never Triggers Automatically

**File:** `argus-workers/tools/post_exploitation.py`, line 755

`PostExploitationOrchestrator` is a full implementation with credential replay, internal probing, and pivot command generation. It is never called by any automated assessment pipeline — only via manual job dispatch.

### 5.2 `ConfidenceEngine.promote()` Never Called

**File:** `Argus-Tui/packages/opencode/src/argus/engagement/confidence.ts`

The confidence engine can promote findings from `LOW → MEDIUM → HIGH → VERIFIED → CONFIRMED` based on evidence and verification status. It is never invoked because browser verification never runs and multi-scanner corroboration is never wired.

### 5.3 State Machine Has States No Pipeline Reaches

**File:** `argus-workers/state_machine.py`

The state machine defines states for `post_exploitation`, `pivot`, and `cleanup`, but no automated pipeline ever transitions to these states. They are reachable only via manual state mutation.

---
## 6. Database Schema / Runtime Mismatches

### 6.1 Fresh Database Crashes on Engagement Creation

**File:** `argus-workers/attack_graph_db.py`

The `init_db()` function creates tables but misses several columns that `save_engagement()` references. On a fresh database, engagement creation throws `OperationalError: no such column`.

### 6.2 Job Schema Column References Out of Sync

**File:** `argus-workers/job_schema.py`

Fields referenced in `dispatch_task.py` don't exist in the schema validator, causing jobs to be rejected at queue time.

---
## 7. Additional Critical Gaps

### 7.1 4 of 7 Verifiers Are Dead Code

**Files:** `ssrf.ts`, `lfi.ts`, `jwt.ts`, `secrets.ts`

These four verifiers exist as fully implemented files but are never imported or called by any pipeline. Only `bola.ts`, `xss.ts`, and `priv-esc.ts` are reachable.

**Fix:** Wire these into `engine.ts` and add their finding types to the orchestrator's verification dispatch logic.

### 7.2 LFI Verifier Hardcodes `status = 200`

**File:** `Argus-Tui/packages/opencode/src/argus/browser/verifiers/lfi.ts`

The LFI verifier hardcodes `status = 200` regardless of the actual HTTP response code. It can't distinguish between a successful LFI (200) and a failed one (404).

### 7.3 JWT Verifier Only Tests localStorage, Not Backend API

**File:** `Argus-Tui/packages/opencode/src/argus/browser/verifiers/jwt.ts`

The JWT verifier injects tokens into localStorage and checks for client-side changes. It never sends the JWT to the backend API to verify the token is actually accepted server-side.

### 7.4 SSRF Verifier Probes Cloud Metadata Directly in Browser

**File:** `Argus-Tui/packages/opencode/src/argus/browser/verifiers/ssrf.ts`

The SSRF verifier navigates to `http://169.254.169.254/latest/meta-data/` inside the Playwright browser context. If running on a cloud VM, this exfiltrates cloud credentials into the test output.

### 7.5 Browser Engine Lacks Comprehensive Stealth/Evasion

**File:** `Argus-Tui/packages/opencode/src/argus/browser/engine.ts`

Only sets `--disable-blink-features=AutomationControlled`. Missing random viewport/user-agent, mouse movement simulation, WebDriver property removal, CDP detection evasion, and canvas fingerprint randomization.

### 7.6 `observe()` Always Returns `responseHeaders: {}`

**File:** `Argus-Tui/packages/opencode/src/argus/browser/engine.ts`

The `observe()` method always returns `responseHeaders: {}` (empty object), even though the browser has access to full response headers. All verifiers and the evidence collector are blind to response headers.

### 7.7 Scope Validator Allows All When `authorized_scope` Is None

**File:** `argus-workers/tools/scope_validator.py`

When `authorized_scope` is `None`, `validate_scope()` returns `True` for any target. A misconfigured scope silently allows scanning any target.

### 7.8 CredentialStore Stores Plaintext Passwords in JSON File

**File:** `argus-workers/secrets_manager.py`

Credentials are stored in a JSON file on disk with no encryption at rest. Any process with filesystem access can read all stored credentials.

### 7.9 All Feature Flags Default to False

**File:** `argus-workers/feature_flags.py`

Every feature flag defaults to `False`. A fresh checkout runs in degraded mode with all advanced features disabled.

**Fix:** Add a `--enable-all` flag or an onboarding prompt that enables recommended flags.

### 7.10 Distributed Lock `_with_reconnect` Passes Wrong Argument Type

**File:** `argus-workers/distributed_lock.py`, lines 105, 171, 245, 262

`_with_reconnect` receives bound Redis methods (e.g., `self.redis.set`) instead of method-name strings. `isinstance(method_name, str)` fails, and the fallback path causes `TypeError` on every call.

---
## 8. Configuration & Infrastructure Dependencies

### 8.1 Requires ~60 External Binaries

Argus depends on: nuclei, nmap, sqlmap, subfinder, httpx, whatweb, nikto, dalfox, commix, testssl, semgrep, bandit, gitleaks, ffuf, arjun, and ~45 more. Each must be installed and in `$PATH`.

### 8.2 Requires PostgreSQL, Redis, LLM API Keys

To run the full stack: PostgreSQL database, Redis queue/broker, at least one LLM API key (OpenAI, Anthropic, or local Ollama), and credential files for browser login.

### 8.3 No Self-Healing at Startup

The orchestrator doesn't verify that all required services are available before starting. It proceeds until a service call fails, then crashes mid-engagement.

**Fix:** Add a `health_check()` phase at startup that verifies all critical binaries are available, PostgreSQL and Redis are reachable, LLM API key is valid and has quota, and credential files exist and are parseable.

---
## Build Order Priority Summary

| Priority | Category | What to Fix | Effort | Impact |
|----------|----------|-------------|--------|--------|
| **P0** | Auth (2.2) | Verifiers fail-closed when login fails | 1–2 days | Eliminates false-positive BOLA/XSS/PrivEsc findings |
| **P0** | Verifiers (7.1) | Wire SSRF/LFI/JWT/Secrets into pipeline | 2–3 days | 4 of 7 verifiers become reachable |
| **P0** | Pipeline (1.1) | Auto-verify findings after scan phase | 3–5 days | Closes the biggest autonomy gap |
| **P0** | LLM (9.2) | Fix circuit breaker threshold vs retry mismatch | 1 day | LLM circuit breaker actually works |
| **P1** | Auth (2.6) | OAuth fallback to token/cookie injection | 2–3 days | OAuth-gated targets become testable |
| **P1** | Auth (2.1) | Positive auth success detection | 2–3 days | Non-English/custom-error targets work |
| **P1** | Chains (3.1) | Insert exploitation phases from attack graph | 4–6 days | Closes the exploit chain loop |
| **P1** | Locks (7.10) | Fix distributed lock method references | 1 day | Concurrent engagements work |
| **P1** | Scope (13.1) | Consolidate duplicate scope logic | 2–3 days | Single source of truth for scope |
| **P1** | LLM (9.6) | Emit alerts when agent falls back to deterministic | 1 day | Operators can detect degraded mode |
| **P1** | LLM (9.1) | Refactor chat/chat_sync/chat_async duplication | 2–3 days | Reduces bug surface by ~400 lines |
| **P2** | Stealth (7.5) | Comprehensive browser evasion | 2–3 days | WAFs won't block immediately |
| **P2** | Schema (6.1) | Fix DB init column mismatches | 1 day | Fresh installs work on first run |
| **P2** | Post-Exploit (5.1) | Auto-trigger post-exploitation from findings | 3–5 days | Moves beyond pure scanning |
| **P2** | LLM (9.3) | Reuse Redis connection for rate limiter | 1 day | Faster LLM calls |
| **P2** | LLM (9.5) | Proper Anthropic API support | 2 days | Anthropic users can use auto-detect |
| **P3** | Evidence (1.3) | Full evidence integrity verification | 1–2 days | Chain-of-custody for findings |
| **P3** | Startup (8.3) | Self-healing health checks at startup | 2–3 days | Faster debugging of config issues |
| **P3** | Encryption (7.8) | Encrypt credential store at rest | 2–3 days | Production security requirement |
| **P3** | Tool Cache (4.4) | Invalidate cache on rerun | 1 day | Accurate rerun results |
| **P3** | Streaming (10.2) | Log dropped events, not just count | 1 day | Visibility into lost events |
| **P3** | Worker (11.1) | Lazy migration execution | 1 day | Worker starts despite bad migrations |
| **P3** | Email (11.3) | Implement scheduled report email delivery | 2–3 days | Scheduled reports actually sent |

### Recommended Sprint Plan

**Sprint 1 (P0):** Fix auth fail-closed + wire 4 dead verifiers + auto-verify after scan + fix LLM circuit breaker → closes the **verification loop**

**Sprint 2 (P1):** OAuth fallback + positive auth detection + insert exploitation phases + consolidate scope logic → closes the **exploitation loop**

**Sprint 3 (P1–P2):** Distributed lock fix + browser stealth + DB schema fix + Redis connection reuse + LLM refactoring → **stability & stealth**

**Sprint 4 (P2–P3):** Auto post-exploitation + evidence integrity + health checks + encryption + streaming fixes + email delivery → **production readiness**
