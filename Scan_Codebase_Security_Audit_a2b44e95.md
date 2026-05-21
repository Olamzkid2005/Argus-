# Comprehensive Codebase Logic & Security Audit Plan

## Objective
Perform an exhaustive, systematic, zero-tolerance audit across the ENTIRE Argus codebase — not limited to scanning functionality. Validate every assumption, conditional, function call, data flow, business rule, and operational sequence. Identify ALL logic gaps, inconsistencies, security vulnerabilities, race conditions, resource leaks, and deviations from expected behavior. Produce a structured findings report with exact file paths, line numbers, severity ratings, and actionable remediation guidance.

## Audit Dimensions (10 Focus Areas)
1. **Control flow logic and conditional branches** — unreachable code, inverted conditions, off-by-one errors, missing else branches
2. **Data validation and sanitization** — missing validation, insufficient sanitization, type confusion, format string bugs
3. **Error handling and exception management** — swallowed exceptions, missing error propagation, incorrect retry logic
4. **State transitions and persistence** — illegal transitions, stale state reads, missing persistence, rollback failures
5. **Inter-component communication** — API contract violations, missing callbacks, async/sync mismatches, serialization errors
6. **Business rules and constraints** — rule bypasses, constraint violations, edge case mishandling
7. **Input/output and data transformations** — encoding issues, truncation, data loss, incorrect parsing
8. **Concurrency and race conditions** — missing locks, atomicity violations, deadlocks, thread-unsafe shared state
9. **Security logic and access controls** — auth bypasses, privilege escalation, injection vulnerabilities, insecure defaults
10. **Configuration and environment handling** — missing env vars, unsafe defaults, secret exposure, feature flag bypasses

## Task 1: Inventory and Read ALL Backend Files
Read and analyze EVERY backend file in `argus-workers/` to understand the full attack surface and logic landscape. No file shall be skipped regardless of size or perceived importance.

### Complete File Inventory Strategy
1. List every `.py` file in `argus-workers/` recursively
2. List every file in `argus-workers/config/`, `argus-workers/database/`, `argus-workers/models/`, `argus-workers/orchestrator_pkg/`, `argus-workers/parsers/`, `argus-workers/custom_rules/`, `argus-workers/templates/`, `argus-workers/utils/`
3. Read every file >0KB, prioritizing by risk but ensuring all are covered
4. Note any files that cannot be read and document why

### 1a. Task Layer (argus-workers/tasks/)
- `tasks/scan.py` — main scan Celery task (run_scan, deep_scan, auth_focused_scan)
- `tasks/repo_scan.py` — repository scanning logic (run_repo_scan, expand_repo_scan, SCA, secret scanning, SAST, SBOM)
- `tasks/base.py` — task context, orchestrator wiring, task_context decorator
- `tasks/utils.py` — engagement options helper (fetch_engagement_scan_options, get_engagement_state, load_recon_context)
- `tasks/analyze.py` — post-scan analysis Celery task
- `tasks/recon.py` — reconnaissance phase that feeds scan inputs
- `tasks/diff.py` — scan diff engine integration
- `tasks/llm_review.py` — LLM-based review of findings
- `tasks/bugbounty.py` — bug bounty mode scanning
- `tasks/self_scan.py` — self-scanning logic
- `tasks/scheduled.py` — scheduled scan dispatch
- `tasks/report.py` — report generation triggered after scans
- `tasks/progress_tracker.py` — scan progress tracking
- `tasks/loader.py` — task loader/discovery

### 1b. Agent Layer (argus-workers/agent/)
- `agent/swarm.py` — multi-agent swarm orchestration (IDORAgent, AuthAgent, APIAgent, SwarmOrchestrator)
- `agent/coordinator.py` — agent coordination logic
- `agent/react_agent.py` — ReAct agent loop implementation
- `agent/agent_prompts.py` — agent prompts (37.5KB, may contain injection vectors)
- `agent/agent_action.py` — agent action definitions
- `agent/agent_result.py` — agent result handling
- `agent/agent_config.py` — agent configuration
- `agent/tool_registry.py` — tool registration and lookup

### 1c. Orchestrator Layer (argus-workers/)
- `orchestrator.py` — main orchestrator dispatch (run_scan, run_repo_scan)
- `orchestrator_pkg/` — pipeline routing, utils, and sub-modules
- `pipeline_router.py` — pipeline routing logic
- `phases.py` — phase definitions and transitions
- `intent_parser.py` — user intent parsing for scans
- `loop_budget_manager.py` — budget enforcement across loops
- `checkpoint_manager.py` — checkpoint save/restore during scans

### 1d. Tool Layer (argus-workers/tools/)
- `tools/web_scanner.py` — primary web scanner (104KB, largest tool, highest risk)
- `tools/tool_runner.py` — tool execution wrapper
- `tools/tool_executor.py` — lower-level execution
- `tools/tool_result.py` — result parsing and normalization
- `tools/tool_cache.py` — caching layer for tool results
- `tools/api_scanner.py` — API scanner
- `tools/api_security_scanner.py` — API security scanner
- `tools/auth_manager.py` — authentication handling for tools
- `tools/scope_validator.py` — scope validation before tool execution
- `tools/circuit_breaker.py` — resilience logic
- `tools/dual_auth_scanner.py` — dual authentication scanning
- `tools/finding_verifier.py` — finding verification
- `tools/llm_detector.py` — LLM-based vulnerability detection
- `tools/llm_payload_generator.py` — payload generation (injection risk)
- `tools/port_scanner.py` — port scanning
- `tools/browser_scanner.py` — browser-based scanning
- `tools/_browser_scan_worker.py` — browser worker subprocess
- `tools/websocket_scanner.py` — WebSocket scanning
- `tools/sbom_generator.py` — SBOM generation
- `tools/definitions/` — tool definitions directory (27 items)

### 1e. Supporting Infrastructure (argus-workers/)
- `state_machine.py` — engagement state transitions
- `job_schema.py` — job validation and schema enforcement
- `distributed_lock.py` — distributed locking for scan coordination
- `dead_letter_queue.py` — failed task handling
- `error_classifier.py` — error classification
- `scan_diff_engine.py` — finding deduplication and diffing
- `post_finding_hooks.py` — hooks fired after finding creation
- `streaming.py` — real-time streaming of scan events
- `tracing.py` — distributed tracing
- `celery_app.py` / `celery_worker_launcher.py` — Celery configuration
- `mcp_server.py` — MCP server integration
- `llm_client.py` / `llm_service.py` / `llm_synthesizer.py` / `llm_report_generator.py` — LLM integrations
- `security_audit.py` — security audit wrapper
- `cvss_calculator.py` — CVSS scoring
- `poc_generator.py` — proof-of-concept generation
- `developer_fix_assistant.py` — fix suggestion logic
- `attack_graph.py` — attack graph construction
- `feature_flags.py` — feature flag evaluation during scans

## Task 2: Inventory and Read ALL Frontend Files
Read EVERY file in `argus-platform/src/` to audit the complete frontend implementation. Scan-depth configuration is one focus area among many.

### Complete File Inventory Strategy
1. List every `.ts`, `.tsx`, `.js`, `.jsx` file in `argus-platform/src/` recursively
2. Read all API routes, pages, components, hooks, lib utilities, types, and middleware
3. Read `next.config.mjs`, `package.json`, `tsconfig.json`, `tailwind.config.ts`
4. Note any files that cannot be read and document why

### 2a. API Routes (argus-platform/src/app/api/)
- `src/app/api/engagements/parse-intent/route.ts` — aggressiveness default
- `src/app/api/engagement/[id]/rescan/route.ts` — rescan with aggressiveness
- `src/app/api/engagement/[id]/route.ts` — engagement detail with budget
- `src/app/api/engagements/route.ts` — engagement list/create
- `src/app/api/reports/generate/route.ts` — report generation budget
- `src/app/api/reports/scheduled/route.ts` — scheduled report budget
- `src/app/api/reports/compliance/route.ts` — compliance report budget
- `src/app/api/settings/route.ts` — scan aggressiveness settings
- `src/app/api/openapi/route.ts` — aggressiveness enum definition
- `src/app/api/scan/` — any scan-specific API routes
- `src/app/api/findings/` — finding routes that may trigger re-scan hooks
- `src/app/api/assets/` — asset routes that feed scan targets

### 2b. Frontend UI Components (argus-platform/src/)
- `src/app/engagements/` — engagement creation/editing forms (scan mode, aggressiveness dropdown)
- `src/app/settings/` — user settings page (scan aggressiveness preference)
- `src/app/dashboard/` — dashboard that may launch quick scans
- `src/components/` — any shared components for scan configuration
- `src/hooks/` — custom hooks that fetch or mutate scan settings
- `src/lib/` — utility functions for scan option validation
- `src/types/` — TypeScript type definitions for scan options

### 2c. Frontend Search Strategy
Use `grep_code` to find all occurrences of the following terms in `argus-platform/src/`:
- `aggressiveness`, `scan_aggressiveness`, `scan_mode`, `agent_mode`
- `max_depth`, `max_cycles`, `budget`
- `default`, `high`, `aggressive` (in scan context)
- `rate_limit_config`
Map every file containing these terms and read each one.

## Task 3: First-Pass Audit — Backend Logic (All 10 Dimensions)
For **every** backend file listed in Task 1, apply all 10 audit dimensions:

### 3a. Input Validation & Injection
- **Command injection** — string concatenation into shell commands (`subprocess`, `os.system`, `os.popen`)
- **Argument injection** — user-controlled values passed as arguments where a leading `-` changes semantics
- **SQL injection** — raw SQL string construction (especially in `tasks/utils.py`, database modules)
- **Path traversal** — user-controlled paths used in `open()`, `os.path.join()`, `subprocess` without sanitization
- **SSRF** — unvalidated URLs passed to `requests`, `urllib`, `git clone`, `subprocess` fetching remote resources

### 3b. Concurrency & State
- **Race conditions** — state transitions without `DistributedLock` or with improper lock scope
- **Double-dispatch** — same engagement enqueued multiple times concurrently
- **State machine bypass** — transitions allowed from illegal states
- **Orphaned tasks** — downstream tasks dispatched even when state transition fails

### 3c. Error Handling & Resilience
- **Bare `except:` clauses** — `except Exception:` or bare `except:` that swallow critical failures
- **Missing return after error** — functions that continue executing after setting error state
- **Unlogged exceptions** — exceptions caught but not logged before being suppressed
- **Celery retry misconfiguration** — tasks that retry infinitely or without backoff

### 3d. Resource Management
- **Unterminated subprocesses** — `Popen` without `wait()`, `kill()`, or context manager
- **Unclosed files** — `open()` without `with` statement or explicit `close()`
- **Memory exhaustion** — unbounded list accumulation, unbounded string building
- **Redis connection leaks** — connections opened without closing or pooling

### 3e. Security Boundaries
- **Authentication bypass** — missing auth checks on API endpoints or Celery task entry points
- **Scope validation bypass** — ways to scan targets outside authorized scope
- **Budget / depth bypass** — ways to exceed `max_cycles`, `max_depth`, or time limits
- **Feature flag bypass** — ways to enable disabled features
- **Privilege escalation** — engagement data visible across organizational boundaries

### 3f. Data Integrity
- **Redis key injection** — unsanitized engagement_id or user input in Redis keys
- **Unsafe deserialization** — `json.loads`, `pickle.loads`, `yaml.load` on untrusted data
- **Sensitive data logging** — secrets, tokens, or PII logged to plaintext
- **Finding tampering** — missing integrity checks on findings stored in DB

## Task 4: First-Pass Audit — Agent Swarm Logic
For `agent/swarm.py`, `agent/coordinator.py`, `agent/react_agent.py`, and related:

### 4a. SwarmOrchestrator
- **ThreadPoolExecutor safety** — `shutdown(wait=False, cancel_futures=True)` behavior and hung-thread cleanup
- **Global timeout vs per-agent timeout** — `per_agent_timeout = max(timeout // max(len(active), 1), 300)` integer division issues when `timeout < 300`
- **Future cancellation limitations** — `future.cancel()` only works for unstarted tasks; verify documentation comment matches reality
- **Concurrent modification** — `all_findings.extend(result)` from multiple threads without locking
- **Deep copy verification** — confirm `copy.deepcopy(recon_context)` is actually immutable-safe (contains nested mutable objects?)

### 4b. Specialist Agents (IDORAgent, AuthAgent, APIAgent)
- **Target URL injection** — target URLs passed directly as shell arguments without validation or escaping
- **Arjun output path collisions** — hardcoded temp filenames (`arjun_idor.json`, `arjun_api.json`, `sqlmap_api.json`) across concurrent engagements
- **JWT tool misuse** — `jwt_tool` with `-C -d` flags on arbitrary targets may be destructive
- **Sqlmap execution** — `sqlmap` running without `--batch` or user confirmation; verify scope re-check before execution
- **Nuclei template path** — `templates_path.exists()` check but no validation of path contents
- **Unbounded target loops** — `for target in targets:` where `targets` can be arbitrarily large

### 4c. ReAct Agent Loop
- **Prompt injection** — user-controlled target URLs or parameters rendered into agent prompts in `agent_prompts.py`
- **Tool output parsing** — LLM parsing of tool output that may contain malicious content
- **Infinite loops** — missing loop termination conditions or budget enforcement in `react_agent.py`
- **Decision logging integrity** — `log_decision` may fail silently

### 4d. Deduplication Logic
- **Fingerprint collisions** — `ScanDiffEngine._fallback_fingerprint()` collision rate and correctness
- **Evidence merging** — `len(str(new_ev)) > len(str(existing_ev))` as evidence-quality heuristic is fragile
- **Confidence comparison** — `float()` conversion failures on malformed confidence values
- **Missing source_agent persistence** — `_overwrite_keys` set may drop critical provenance data

## Task 5: First-Pass Audit — Repository Scanning Logic
For `tasks/repo_scan.py`, `tools/sbom_generator.py`, and related SCA/SAST integrations:

### 5a. Repository Acquisition
- **Git clone SSRF** — `repo_url` passed to `git clone` without URL scheme validation, host allowlisting, or port restriction
- **Local path injection** — `repo_url` may be a local file path (`file:///etc/passwd`) leading to arbitrary file read
- **Submodule exploitation** — cloned repository may contain malicious submodules that execute code
- **Post-checkout hooks** — `.git/hooks` execution after clone

### 5b. SCA Tool Execution (npm, pip, govulncheck)
- **npm audit** — runs in cloned repo directory; malicious `package.json` scripts may execute on `npm audit`
- **pip-audit** — runs in cloned repo; verify isolation from host Python environment
- **govulncheck** — Go module resolution may fetch arbitrary remote packages
- **Command argument lists** — verify all subprocess calls use list form, not shell strings

### 5c. SAST Tool Execution (bandit, eslint, gosec)
- **Bandit** — `bandit -r repo_path` where `repo_path` could contain spaces or special characters
- **ESLint** — `repo_path.startswith("-")` check exists; verify `npx eslint -- repo_path` uses `--` separator correctly
- **gosec** — `gosec -fmt=json repo_path` argument injection risk
- **Semgrep** — custom rules path validation (`custom_rules_path`, `additional_rules_path`)

### 5d. Secret Scanning
- **Regex limitations** — `SECRET_PATTERNS` may miss secrets (high false-negative rate) or match benign strings (high false-positive rate)
- **AWS secret key pattern** — `(?<![A-Za-z0-9/+])[A-Za-z0-9/+]{40}(?![A-Za-z0-9/+=])` may match SHA-1 hashes, git commit hashes
- **Git history truncation** — `max_git_output_bytes = 100MB` may truncate mid-secret, causing misses
- **Memory usage** — `process.stdout` read line-by-line but patch accumulation in `patch_lines` may grow unbounded

### 5e. License & SBOM
- **License detection** — `_match_license()` regexes may match partial text; verify accuracy
- **SBOM path safety** — `os.path.join(repo_path, "sbom-cyclonedx.json")` may traverse if `repo_path` is controlled
- **Dependency data trust** — `package-lock.json` parsed without schema validation

### 5f. State & Error Handling
- **Lock scope** — `LockContext(lock, engagement_id)` used but verify lock timeout and deadlock scenarios
- **State transition on exception** — `_get_engagement_state()` fallback state may be stale
- **Missing `safe_transition` return check** — `safe_transition` return value ignored in some paths
- **Trace ID generation** — `tracing_manager.generate_trace_id()` used when not provided; verify collision resistance

## Task 6: First-Pass Audit — Frontend Logic (All 10 Dimensions)
For every frontend file identified in Task 2, apply all 10 audit dimensions with frontend-specific checks:

### 6a. Control Flow & Conditional Logic
- **Unreachable code** — dead branches, early returns that make subsequent code unreachable
- **Inverted conditions** — `!condition` used where `condition` was intended
- **Missing else branches** — implicit else behavior that may cause unexpected state
- **Switch/case fallthrough** — missing breaks in route handlers or reducers
- **Race conditions in UI** — form submission while previous request is in flight

### 6b. Data Validation & Sanitization
- **Missing server-side validation** — `aggressiveness` value accepted without enum check or length limit
- **Default fallback chain** — verify fallback logic (`body.scanAggressiveness || body.scan_aggressiveness || 'default'`) cannot be bypassed by sending falsy-but-valid values
- **Budget override** — `budget: { max_cycles: 5, max_depth: 3 }` hardcoded in some routes; verify this cannot be overridden by client input
- **Scheduled scan injection** — cron expression parsing and validation in scheduled routes
- **Type confusion** — `aggressiveness` typed as `string` in some places, enum in others; verify consistency
- **Rate limit config** — `rate_limit_config` passed through without validation of nested fields
- **Authorization proof** — verify authorization proof is validated, not just stored

### 6c. Error Handling & Exception Management
- **Uncaught promise rejections** — `fetch()` without `.catch()` or `try/catch`
- **Missing error boundaries** — React components that may crash without recovery
- **Silent failures** — errors logged to console but not shown to user
- **Incorrect HTTP status handling** — treating 404 same as 500, or ignoring non-2xx

### 6d. State Transitions & Persistence
- **Client-side state desync** — React state diverges from server state after mutation
- **Race conditions on mutation** — optimistic updates not rolled back on failure
- **LocalStorage/SessionStorage** — unvalidated data read from storage; XSS via stored values
- **URL state desync** — query params out of sync with actual filter state

### 6e. Inter-Component Communication
- **Prop drilling gaps** — data passed through layers without validation at boundaries
- **Context API misuse** — missing Provider, stale context values
- **Event handler leaks** — unsubscribed event listeners or WebSocket connections
- **Server/Client component boundary** — data fetched in Server Component but not passed correctly to Client Component

### 6f. Business Rules & Constraints
- **Authorization checks** — page-level and API-route-level auth validation
- **Role-based access** — admin vs user feature gates
- **Workflow enforcement** — preventing actions on engagements in wrong state
- **Quota enforcement** — scan limits, report limits enforced only client-side

### 6g. I/O & Data Transformations
- **Encoding issues** — URL encoding, base64, JSON parsing without schema validation
- **Date/time handling** — timezone inconsistencies, format mismatches
- **File upload validation** — missing type/size checks, path traversal via filenames
- **CSV/Excel export** — injection vulnerabilities in generated spreadsheets

### 6h. Concurrency & Race Conditions
- **Request deduplication** — identical simultaneous requests not deduplicated
- **Stale closure** — `useEffect` or callbacks capturing stale state
- **WebSocket reconnection** — duplicate connections on reconnect
- **Polling intervals** — overlapping poll requests

### 6i. Security & Access Controls
- **Middleware auth gaps** — `middleware.ts` bypass scenarios, public routes that should be protected
- **CSRF protection** — missing or incorrect CSRF token handling
- **XSS vectors** — `dangerouslySetInnerHTML`, unescaped user input in JSX
- **CSP violations** — inline scripts/styles that violate Content Security Policy
- **Secrets in frontend** — API keys, tokens exposed in client-side bundle

### 6j. Configuration & Environment
- **Environment variable exposure** — `NEXT_PUBLIC_` vars that should be server-only
- **Feature flag evaluation** — flags evaluated client-side that control security-sensitive features
- **Build-time vs runtime config** — values baked at build that should be runtime
- **Redis key construction** — `` `settings:${email}:scan_aggressiveness` `` — verify email is sanitized
- **Type safety on retrieval** — Redis returns strings; verify proper parsing before use
- **Cross-user leakage** — verify settings are scoped to authenticated user only

## Task 7: Read Remaining Architecture & Configuration Files
Read every file in both projects that has not been read in Tasks 1–6. This includes deployment configs, Docker files, CI/CD, documentation, and any other code-bearing files. No file shall be skipped.

### 7a. Orchestrator & Pipeline
- `argus-workers/phases.py` — phase enum definitions and transition rules
- `argus-workers/pipeline_router.py` — routing logic between scan types
- `argus-workers/orchestrator.py` — main orchestrator (run_scan, run_repo_scan implementations)
- `argus-workers/orchestrator_pkg/` — all sub-modules

### 7b. Budget & State Management
- `argus-workers/loop_budget_manager.py` — budget tracking and enforcement
- `argus-workers/checkpoint_manager.py` — checkpoint serialization/deserialization
- `argus-workers/state_machine.py` — full state machine implementation
- `argus-workers/distributed_lock.py` — lock implementation and timeout behavior

### 7c. Error Handling & Observability
- `argus-workers/dead_letter_queue.py` — dead letter processing
- `argus-workers/error_classifier.py` — error classification logic
- `argus-workers/post_finding_hooks.py` — hooks executed on finding creation
- `argus-workers/streaming.py` — event streaming to frontend
- `argus-workers/tracing.py` — trace context propagation
- `argus-workers/health_monitor.py` — worker health checks

### 7d. Diff & Deduplication
- `argus-workers/scan_diff_engine.py` — diffing and fingerprinting algorithms
- `argus-workers/diff.py` — diff task integration

### 7e. LLM & Intelligence
- `argus-workers/llm_client.py` — LLM API client
- `argus-workers/llm_service.py` — LLM service abstraction
- `argus-workers/llm_synthesizer.py` — result synthesis
- `argus-workers/llm_report_generator.py` — report generation
- `argus-workers/intelligence_engine.py` — threat intelligence integration
- `argus-workers/llm_parser_fallback.py` — fallback parsing
- `argus-workers/ai_explainer.py` — AI explanation logic
- `argus-workers/ai_vuln_scanner.py` — AI-based vulnerability scanning

### 7f. Frontend Infrastructure
- `argus-platform/src/middleware.ts` — request middleware (auth, rate limiting)
- `argus-platform/src/lib/` — all utility files (25 files, 3 subdirs)
- `argus-platform/src/types/` — type definitions
- `argus-platform/src/hooks/` — all custom hooks
- `argus-platform/src/components/` — all shared components
- `argus-platform/src/app/api/` — all API routes not yet examined

### 7g. Configuration & Deployment
- `argus-workers/config/` — all configuration files
- `argus-workers/secrets_manager.py` — secret retrieval and caching
- `argus-workers/feature_flags.py` — feature flag evaluation
- `argus-workers/di_container.py` — dependency injection container
- `argus-workers/snapshot_manager.py` — snapshot management
- `argus-workers/shutdown_handler.py` — graceful shutdown
- `argus-platform/next.config.mjs` — Next.js configuration
- `argus-platform/package.json` — dependency audit for known vulnerabilities

### 7h. Database & Models
- `argus-workers/database/` — all database modules (connection, models, migrations)
- `argus-workers/models/` — data models
- `argus-platform/db/schema.sql` — database schema
- `argus-platform/db/migrations/` — all migration files

### 7j. Deployment & Infrastructure
- `deployment/` — Caddyfile, nginx.conf
- `argus-workers/Dockerfile` — container security, exposed ports, user privileges
- `argus-platform/Dockerfile` — container security, build context
- `.github/workflows/ci.yml` — CI/CD pipeline, secret exposure, test gaps
- `Makefile` — build commands, unsafe operations
- `start-argus.sh` / `stop-argus.sh` — startup/shutdown scripts
- `.env.example` — check for default secrets, insecure defaults
- `.gitleaks.toml` — secret scanning configuration

### 7k. Documentation & Specs
- `docs/` — architecture docs for inconsistencies with implementation
- `README.md` files — check for exposed endpoints, default credentials
- `ARGUS-CODEBASE-OVERVIEW.md` — cross-reference with actual code

### 7l. Tests
- `argus-workers/tests/` — all 52+ test files for scanning logic
- `argus-platform/__tests__/` — frontend tests
- `argus-platform/tests/` — additional test suites
- Review tests for missing coverage that could hide bugs
- Check for tests that assert incorrect behavior (false negatives)

## Task 8: Second-Pass Audit — Cross-Cutting Concerns
After completing Tasks 1–7, perform a second pass focusing on cross-file and cross-module issues that only become visible with full context:

### 8a. Cross-File Consistency
- **Validation gaps** — one file validates input, another reads the same input without validation
- **Budget enforcement** — `loop_budget_manager.py` enforces limits, but do `tools/web_scanner.py` or `agent/swarm.py` bypass them?
- **Scope checks** — `scope_validator.py` validates targets, but do all tools call it?
- **Auth checks** — `middleware.ts` checks auth, but do Celery tasks verify engagement ownership?

### 8b. State Machine Integrity
- **Illegal transitions** — can `scanning` -> `failed` -> `analyzing` occur via race conditions?
- **Double transition** — can two concurrent tasks transition the same engagement simultaneously?
- **Terminal state escapes** — can a `completed` engagement be re-scanned or modified?

### 8c. Data Flow Audit
- **Engagement ID trust** — is `engagement_id` ever derived from user input without validation?
- **Target propagation** — trace a target URL from frontend form -> API route -> Celery task -> tool execution, checking for validation at each hop
- **Aggressiveness propagation** — trace `aggressiveness` from frontend -> API -> task -> orchestrator -> tool, verifying no override or default injection bugs

### 8d. Tool Execution Chain
- **Tool definitions** — read all files in `tools/definitions/` to verify they match `tool_runner.py` expectations
- **Tool cache poisoning** — can malicious input poison `tool_cache.py` entries?
- **Circuit breaker bypass** — `circuit_breaker.py` may be bypassed by direct `subprocess` calls

### 8e. LLM Integration Risks
- **Prompt injection via findings** — tool output containing malicious content rendered into LLM prompts
- **LLM output trust** — LLM-generated payloads or findings accepted without validation
- **Token budget exhaustion** — missing token limit enforcement in `llm_client.py`
- **API key exposure** — LLM API keys logged or exposed in error messages

### 8f. Frontend-Backend Contract
- **API schema drift** — frontend sends fields backend no longer accepts, or vice versa
- **TypeScript runtime gaps** — types assert safety but runtime validation is missing
- **Next.js App Router specifics** — Server Component vs Client Component data flow for scan settings

## Task 9: False-Positive Filtering
Apply rigorous filtering to every finding before inclusion in the final report.

### 9a. Reachability Analysis
- **Attack surface** — can an unauthenticated or authenticated user trigger the vulnerable code path?
- **Internal-only exclusion** — code paths reachable only by admin/operators with direct server access are lower priority unless they cascade
- **Celery task exposure** — Celery tasks triggered via API routes are reachable; tasks with no API trigger are internal

### 9b. Mitigation Verification
- **Defense in depth** — verify no other layer provides equivalent protection (e.g., middleware auth, reverse proxy, WAF)
- **Call-chain audit** — trace the full call stack to confirm the vulnerability is not blocked upstream
- **Environment context** — consider Docker network isolation, non-root execution, read-only filesystems

### 9c. Severity Calibration
- **Critical** — Remote code execution, authentication bypass, data exfiltration, complete system compromise
- **High** — Command injection, SQL injection, SSRF, path traversal, privilege escalation
- **Medium** — Missing input validation, race conditions, information disclosure, resource exhaustion
- **Low** — Code quality issues, missing logging, minor logic gaps with no security impact

### 9d. Status Assignment
For each finding, assign one of:
- **Confirmed** — code review proves the issue exists and is reachable
- **Likely** — strong indicators but requires dynamic testing or deeper context to confirm
- **False Positive** — issue appears real but is mitigated by code not visible in the immediate block; document the mitigation

### 9e. Documentation Requirement
Every filtered-out finding must still be documented in an appendix with:
- Original description
- Reason for exclusion
- Mitigating factor or context that invalidates the finding

## Task 10: Compile Results File
Write a comprehensive structured markdown report to `/Users/mac/Documents/Argus-/COMPREHENSIVE_AUDIT_RESULTS.md`.

### 10a. Report Structure
```
# Argus Scanning Functionality Security Audit Report

## 1. Executive Summary
- Total issues found
- Breakdown by severity (Critical / High / Medium / Low)
- Breakdown by category (Security / Logic / Race Condition / Resource Leak / Quality)
- Top 5 most critical findings with one-line descriptions

## 2. Methodology
- Files examined (full list with counts)
- Tools used (static analysis, grep, manual review)
- Audit passes completed
- False-positive filtering criteria applied

## 3. Findings
### 3.1 [Critical/High/Medium/Low] — <Short Title>
- **File(s):** `path/to/file.py` (lines X-Y)
- **Issue Type:** Security Bug / Logic Gap / Race Condition / Resource Leak / Input Validation / etc.
- **Severity:** Critical / High / Medium / Low
- **Status:** Confirmed / Likely / False Positive
- **Description:** Detailed explanation of the issue
- **Evidence:** Exact code snippet or reproduction steps
- **Impact:** What an attacker could achieve or what failure mode occurs
- **Recommendation:** Concrete, actionable fix with pseudocode or patch suggestion
- **References:** Related issues, CVEs, or secure coding guidelines

## 4. Cross-File Issue Map
| Issue ID | Primary File | Related Files | Relationship |
|----------|--------------|---------------|--------------|

## 5. Remediation Roadmap
### Immediate (Critical/High — fix within 48 hours)
### Short-term (High/Medium — fix within 2 weeks)
### Long-term (Medium/Low — fix within 1 month)

## 6. Appendix A: Filtered Findings (False Positives)
| Finding | Reason for Exclusion | Mitigating Factor |

## 7. Appendix B: Files Not Audited (if any)
| File | Reason |
```

### 10b. Quality Requirements
- Every finding must cite exact file paths and line numbers
- Code snippets must be verbatim (copy-paste from source)
- Recommendations must be specific enough to implement without further research
- Cross-references must link related issues across modules
- No vague or generic advice (e.g., "validate input" without specifying how)

## Task 11: Post-Audit Verification
Before finalizing the report:
- Re-read every finding to confirm line numbers are accurate
- Verify no file was skipped due to size or complexity
- Ensure findings are ordered by severity, not discovery order
- Confirm the report is self-contained and actionable without additional context

## Expected Timeline
This is a large multi-file audit spanning 70+ backend files and 40+ frontend files.
Estimated 10–15 focused analysis rounds before compilation, plus 2 rounds of false-positive filtering and 1 round of report refinement.
