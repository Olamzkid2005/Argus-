# Argus Autonomous Red Team Readiness Review

**Date:** 2026-06-28  
**Scope:** Full codebase review of `Argus-Tui/packages/opencode/src/argus/` and `argus-workers/`  
**Objective:** Identify anything that prevents Argus from operating as a fully autonomous red team tester.

---

## Executive Verdict

**Argus is not yet a fully autonomous red team tester.** It is a capable, LLM-assisted security scanner orchestrator with strong scaffolding, but it lacks the core faculties required for unsupervised, goal-driven red teaming: dynamic planning, exploit chaining, post-exploitation, resilient self-healing, and autonomous verification.

The codebase divides into two runtimes:

- **TypeScript CLI/TUI** (`Argus-Tui/packages/opencode/src/argus/`) — user-facing command layer, planner, workflow runner, evidence collector.
- **Python workers** (`argus-workers/`) — MCP tool server, ReAct agent, intelligence engine, orchestration.

Both sides contain blockers. This document provides a consolidated, severity-ranked audit.

---

## CRITICAL Blockers

### 1. Autonomy features are disabled by default

- **Files:** `src/argus/config/feature-flags.ts:30-37`, `argus.config.yaml:6-11`
- **Issue:** Every V5 autonomy feature (`workflow_registry`, `engagement_store`, `approval_gates`, `llm_finding_analysis`, `encryption_at_rest`) defaults to `false`. A fresh checkout runs in degraded mode.
- **Why it blocks autonomy:** An autonomous run cannot start without manual config edits or env vars.
- **Fix:** Add an `ARGUS_AUTONOMOUS=1` profile that enables required flags, and fail hard in headless mode if they are off.

### 2. Approval gates cannot be programmatically approved for destructive work

- **Files:** `src/argus/workflows/approval.ts:65-111`
- **Issue:** In non-TTY mode, destructive gates are auto-skipped; in TTY mode the run blocks for 30 seconds waiting for human input. There is no `--auto-approve`, `ARGUS_AUTO_APPROVE`, or policy override.
- **Why it blocks autonomy:** Real red-team work includes destructive/privilege-escalation phases. The system either skips them or hangs.
- **Fix:** Implement an explicit autonomous-approval policy with audit logging, separate from the TTY heuristic.

### 3. The planner is static and cannot chain exploits

- **Files:** `src/argus/planner/planner.ts`, `src/argus/planner/replan-rules.ts`, `src/argus/planDeterministic.ts`
- **Issue:** Plans are chosen from YAML workflows by target type. `replan` maps only eight finding subtypes to single capabilities. There is no attack graph traversal, conditional sequencing, or LLM-driven planning. A SQLi finding does not trigger data-exfiltration; SSRF does not trigger cloud-metadata exploitation.
- **Why it blocks autonomy:** Autonomous red teaming requires dynamic goal generation and multi-step exploit chains.
- **Fix:** Build a rule/LLM attack planner with prerequisite/impact edges and support `requires_findings` phase prerequisites.

### 4. MCP server replanning is a no-op

- **Files:** `argus-workers/mcp_server.py:785-790`
- **Issue:** `_replan()` literally returns `{"done": True, "reasoning": "Plan complete"}`. The orchestrator never reacts to `stuck`, `new_finding`, or `phase_complete` triggers.
- **Why it blocks autonomy:** The Python side cannot adapt its plan based on findings.
- **Fix:** Wire `_replan()` to the LLM service and session observations.

### 5. No post-exploitation, lateral movement, or pivoting

- **Files:** `argus-workers/attack_graph.py`, `runtime/workflows/`, `tools/dual_auth_scanner.py`
- **Issue:** Attack chain detection is limited to static templates. After confirming a foothold, the system does not extract tokens/credentials, replay them elsewhere, scan internal ranges, or pivot through compromised endpoints.
- **Why it blocks autonomy:** Full red-team autonomy requires "find creds → replay elsewhere → expand scope → repeat."
- **Fix:** Add a `post_exploitation` phase/workflow with credential replay and internal probing under scope gates.

### 6. Hard exploration budgets prevent deep operation

- **Files:** `argus-workers/loop_budget_manager.py`, `state_machine.py`, `config/constants.py`
- **Issue:** Defaults: `max_cycles=5`, `max_depth=3`, `max_llm_reviews=50`, agent max 10 iterations, $0.25/engagement LLM cost cap. These are hard ceilings with no autonomous continuation logic.
- **Why it blocks autonomy:** Deep targets need many recon→scan→analyze loops.
- **Fix:** Make budgets dynamic — let the agent propose continuation rationale when budget is low, with policy-based auto-approval.

### 7. Browser automation cannot handle modern authentication

- **Files:** `src/argus/browser/login.ts`, `argus-workers/tools/scripts/playwright_*.py`
- **Issue:** Auth detection uses HTML regex (`password`, `login`) and fills the first text/password inputs. OAuth, SAML, SSO, MFA, WebAuthn, CAPTCHA, and dynamically rendered forms fail. Success heuristic is `"/login" not in current.lower()`.
- **Why it blocks autonomy:** Most real targets use modern identity flows.
- **Fix:** Add credential-role mapping with explicit selectors, token/session injection, and auth-failure signals.

### 8. No automated verification in the assessment pipeline

- **Files:** `argus-workers/tools/assessment_orchestrator.py`, `src/argus/commands/verify.ts`
- **Issue:** The orchestrator never invokes browser verification. `verify` is exposed only as a manual CLI command. The confidence engine rule for `CONFIRMED` is `condition: () => false`.
- **Why it blocks autonomy:** Findings remain scanner-reported; the system cannot self-confirm exploitability.
- **Fix:** Wire verification into the orchestrator for findings above a threshold and promote `CONFIRMED` when verification passes.

### 9. Browser engine does not capture network evidence

- **Files:** `src/argus/browser/engine.ts`, `src/argus/browser/observer.ts`, `src/argus/evidence/collector.ts`
- **Issue:** `observe()` returns empty response headers. HAR capture is off by default and never enabled. Verifiers store stubs like `GET ${url} [label]` instead of real request/response objects.
- **Why it blocks autonomy:** Without artifacts, findings cannot be reproduced, proven, or audited.
- **Fix:** Instrument Playwright with `record_har_path` and persist full request/response evidence.

### 10. Verifiers use hardcoded inputs and cannot adapt to target shape

- **Files:** `src/argus/browser/verifiers/xss.ts`, `verifiers/bola.ts`, `verifiers/priv-esc.ts`
- **Issue:** XSS payload is fixed `<script>alert('xss')</script>`; BOLA uses `/api/resource`; privilege escalation defaults to `/admin`; roles are substring-matched to four archetypes.
- **Why it blocks autonomy:** Real targets have custom routes, GraphQL, and role names.
- **Fix:** Feed endpoint inventory from recon into verifiers and support arbitrary role/payload configuration.

### 11. Encryption key cache TTL breaks long automation

- **Files:** `src/argus/storage/encryption.ts:528,622-627`, `src/argus/engagement/store.ts:366-374`
- **Issue:** Master key cache expires after 5 minutes; per-engagement DB handles close after 5 minutes idle. Reopening an encrypted engagement requires the cached key. Non-macOS requires `ARGUS_KEY_PASSPHRASE` or an interactive prompt.
- **Why it blocks autonomy:** Long-running or resumable headless runs fail when the key expires.
- **Fix:** Preload/refresh keys in daemon mode; support cloud KMS/HSM/Vault; extend TTL for service accounts.

### 12. Worker bridge has no true deterministic fallback when the worker dies

- **Files:** `src/argus/bridge/mcp-client.ts`, `src/argus/bridge/supervisor.ts`
- **Issue:** After three worker restarts, the bridge throws and halts. No alternative executor or degraded-mode stub exists.
- **Why it blocks autonomy:** A persistent worker crash permanently stops the engagement.
- **Fix:** Implement a degraded mode that returns stub results, queues work, or routes to an alternative executor.

### 13. Manual secret/key provisioning prevents zero-touch deployment

- **Files:** `docker-compose.yml`, `.env.example`, `argus-workers/config/startup_guard.py`
- **Issue:** Docker Compose aborts unless `POSTGRES_PASSWORD` and `DATABASE_URL` are set. The startup guard only logs warnings for placeholder credentials.
- **Why it blocks autonomy:** A human must edit files before the first container starts.
- **Fix:** Provide an init container/bootstrap script that generates and stores secrets automatically.

---

## HIGH Blockers

### 14. Replan phases are appended instead of inserted next

- **Files:** `src/argus/workflow-runner.ts:349-375`, `src/argus/commands/resume.ts:221-243`
- **Issue:** Code comment says it inserts at `i + 1`, but it actually `push()`es to the end.
- **Why it blocks autonomy:** Adaptive response is delayed until the original static plan finishes.
- **Fix:** Use `splice(i + 1, 0, ...)` and update indices.

### 15. No mid-phase checkpointing

- **Files:** `src/argus/workflow-runner.ts:288-379`, `src/argus/engagement/recovery.ts`, `argus-workers/checkpoint_manager.py`
- **Issue:** Phase state is only persisted after the phase completes. Resume reconstructs the plan from scratch and cannot continue inside a phase.
- **Fix:** Persist per-tool state and integrate the checkpoint manager.

### 16. Authentication detection is URL-heuristic only

- **Files:** `src/argus/planner/strategy.ts:31-38`, `workflow-runner.ts:234-237`
- **Issue:** Only checks URL path keywords and sprays credentials into every phase.
- **Fix:** Detect auth from recon signals (401/403, login pages, OpenAPI security schemes) and route credentials only to matching phases.

### 17. LLM-driven executor is dead code

- **Files:** `src/argus/planner/executor.ts:182-184,299-458`, `workflows/*.yaml`
- **Issue:** `executeHybrid` implements an autonomous loop, but no workflow phase uses `execution: llm_driven`.
- **Fix:** Add an adaptive execution mode to workflow YAML and have the planner emit it.

### 18. Error recovery retries the same tool; no tactic adaptation

- **Files:** `src/argus/planner/executor.ts:479-573`, `argus-workers/error_classifier.py`, `tools/tool_runner.py`
- **Issue:** Errors are classified and retried, but the system does not switch payloads, slow down on rate limits, re-login on auth errors, or substitute alternative tools.
- **Fix:** Add an `ErrorRecoveryPlanner` that maps error classification to recovery strategies.

### 19. Rigid tool arguments / no payload evolution

- **Files:** `argus-workers/tools/llm_payload_generator.py`, `agent/react_agent.py`, `mcp_server.py`
- **Issue:** Tool args come from fixed YAML schemas; payload generator is capped at 2 payloads; no feedback loop mutates payloads based on responses.
- **Fix:** Build a feedback-driven payload evolution loop.

### 20. Static attack-chain templates

- **Files:** `argus-workers/attack_graph.py`, `chain_exploit_generator.py`
- **Issue:** Only 8 hardcoded chain templates; no runtime engine validates each link.
- **Fix:** Replace with graph-search chain builder over prerequisites/impacts.

### 21. Verification coverage is narrow and feature-flagged

- **Files:** `argus-workers/tools/finding_verifier.py`, `tools/verification_agent.py`
- **Issue:** Only SQLi, XSS, and open-redirect have verifiers. `FINDING_VERIFICATION` defaults off.
- **Fix:** Expand verifiers and enable by default for HIGH/CRITICAL findings.

### 22. PoC/chain generation is narrow and LLM-dependent

- **Files:** `argus-workers/poc_generator.py`, `chain_exploit_generator.py`
- **Issue:** Only HIGH/CRITICAL findings with confidence ≥ 0.75; only 4 templates; no deterministic fallback.
- **Fix:** Add deterministic templates for more classes and a best-effort mode.

### 23. Short observation window limits long-horizon reasoning

- **Files:** `argus-workers/agent/react_agent.py`, `runtime/engagement_state.py`
- **Issue:** History caps at 50 entries / 2000 chars; LLM sees only the last ~6 tool outputs.
- **Fix:** Implement tiered memory: recent observations + summarizer + target profile.

### 24. State machine is linear with limited loop-backs

- **Files:** `argus-workers/state_machine.py`, `phases.py`
- **Issue:** Valid transitions are hardcoded; no `scanning → recon` on new-asset discovery, no `investigate`/`pivot` sub-states.
- **Fix:** Add richer transitions and goal-oriented sub-states.

### 25. No hypothesis generation or root-cause analysis

- **Files:** `argus-workers/runtime/engagement_state.py`, `tools/correlation/root_cause.py`, `intelligence_engine.py`
- **Issue:** `hypotheses` field is initialized but never used. Root-cause grouping is trivial tuple dedup.
- **Fix:** Add a `HypothesisEngine` that emits ranked hypotheses and verification steps.

### 26. Single-node Postgres/Redis with no fallback

- **Files:** `docker-compose.yml`, `argus-workers/database/connection.py`, `config/redis.py`
- **Issue:** No replication, failover, or read-replica support.
- **Fix:** Deploy replication/Sentinel/Cluster and update connection code.

### 27. Redis-only DLQ/locks/heartbeats cause silent data loss on outage

- **Files:** `argus-workers/dead_letter_queue.py`, `distributed_lock.py`, `health_monitor.py`, `celery_app.py`
- **Issue:** DLQ, locks, and heartbeats depend on a single Redis. No fallback to Postgres/filesystem.
- **Fix:** Implement DB-backed DLQ and advisory-lock fallback; add Redis Sentinel support.

### 28. Graceful shutdown leaks locks and kills long scans

- **Files:** `argus-workers/shutdown_handler.py`, `distributed_lock.py`
- **Issue:** 30-second default force-exit; locks not released; DLQ not flushed.
- **Fix:** Increase default timeout; release locks and flush DLQ on shutdown.

### 29. Tool `call_tool` treats any non-zero exit code as failure

- **Files:** `argus-workers/mcp_server.py:624-651`
- **Issue:** Many security tools return non-zero on findings or down hosts.
- **Fix:** Let tool definitions declare expected return codes or parse findings regardless of exit code.

### 30. Engagement store dual-DB architecture risks inconsistent state

- **Files:** `src/argus/engagement/store.ts`
- **Issue:** Reads fall back to root DB; writes create/migrate per-engagement DB. A crash between writes can leave split state.
- **Fix:** Enforce a single storage path per engagement and remove runtime fallback.

### 31. Evidence manifests lack chain-of-custody metadata

- **Files:** `src/argus/evidence/types.ts`, `evidence/collector.ts`, `evidence/store.ts`
- **Issue:** Manifests lack operator identity, source tool, phase, target URL, parent finding, and previous package reference.
- **Fix:** Extend manifest schema and add signed audit log references.

### 32. `EvidenceCollector` silently discards failures

- **Files:** `src/argus/evidence/collector.ts`
- **Issue:** Evidence operations are wrapped in `.catch(() => null)`; failures are invisible.
- **Fix:** Log failures to the engagement audit log and surface them in verifier results.

### 33. Credential store plaintext JSON with no rotation

- **Files:** `src/argus/engagement/credentials.ts`
- **Issue:** Plaintext JSON credentials; no validation, expiration, or rotation; `clear()` does not wipe the file.
- **Fix:** Integrate with OS keychain/secret service and support rotation hints.

### 34. CWE formatting bug in normalizer

- **Files:** `argus-workers/parsers/normalizer.py:432-433`
- **Issue:** `cwe = "CWE-%s", cwe` creates a tuple and will crash.
- **Fix:** Correct to `cwe = f"CWE-{cwe}"`.

---

## MEDIUM / Low Blockers

- **Feature flags ignore DB source** — global `FeatureFlags` is created without a DB connection (`argus-workers/feature_flags.py`).
- **Config loader ignores env/CLI precedence** — `src/argus/config/loader.ts` only reads project config.
- **No schema migration runner** — only bind-mounted init scripts.
- **Settings repository loses encryption key** when env var is absent.
- **Celery global time limits** (5m soft / 10m hard) can abort long scans.
- **Dockerfile healthcheck** only checks Celery, not dependencies.
- **Worker health monitor is passive** — records metrics but never triggers restart.
- **Report generator is static** — no embedded evidence or adaptive narrative.
- **Encrypted file magic-byte heuristic** is weak (`fd[0] & 0x01`).
- **DOM diff is line-based and noisy**.

---

## Recommended Roadmap to Full Autonomy

### Phase 1 — Stabilize the Foundation (0–4 weeks)

1. Fix concrete bugs: CWE tuple, feature-flag DB wiring.
2. Implement full config precedence (CLI > env > project > user > defaults).
3. Enable an `ARGUS_AUTONOMOUS=1` profile that flips required flags.
4. Add KMS/Vault-backed key provider and remove 5-minute TTL for daemon mode.
5. Add Postgres-backed DLQ/lock fallback and proper shutdown finalizers.

### Phase 2 — Make Planning Dynamic (4–8 weeks)

1. Replace the no-op `_replan()` with LLM/rule-based replanning.
2. Insert replan phases immediately after the triggering phase (`splice`, not `push`).
3. Wire the existing `executeHybrid` agent loop into workflow YAML.
4. Implement attack-graph planning with prerequisite/impact edges.
5. Add hypothesis generation and root-cause analysis.

### Phase 3 — Autonomous Verification & Exploitation (8–14 weeks)

1. Integrate browser verification into the orchestrated pipeline.
2. Expand verifiers to SSRF, IDOR/BOLA, LFI, JWT, secrets.
3. Feed recon endpoint inventory into verifiers; support arbitrary roles/payloads.
4. Capture HAR + request/response evidence automatically.
5. Add post-exploitation modules: token extraction, credential replay, internal probing.

### Phase 4 — Resilience & Scale (14–20 weeks)

1. Mid-phase checkpointing and inside-phase resume.
2. Worker bridge true degraded mode.
3. Postgres/Redis high availability.
4. Headless daemon/scheduler mode.
5. Health endpoints and self-healing probes.

---

## Bottom Line

Argus today is best described as a **human-supervised, LLM-assisted scanner orchestrator**. It can run a predefined security workflow against a target, collect findings, and produce a report, but it cannot yet:

- Reason about findings and autonomously decide what to do next.
- Chain exploits or move laterally.
- Self-verify most finding classes without human invocation.
- Survive worker crashes or long-running encrypted sessions without human intervention.
- Deploy itself without manual secret/config setup.

Until the CRITICAL and HIGH items above are addressed, Argus should not be expected to run unsupervised full-lifecycle red team engagements. It is a strong foundation, but the gap from "orchestrator" to "autonomous red-team agent" is substantial and architectural, not just a matter of tuning.

---

# Part 2 — Deep-Dive Findings

This section captures additional blockers discovered during a second, line-by-line pass through the workflow/tool YAMLs, LLM/agent code, concurrency layer, and operational/test infrastructure. Many of these are concrete bugs that would cause autonomous runs to crash, hang, or silently produce wrong results.

---

## 1. Workflow & Tool Definition Defects

### CRITICAL — Playwright YAML schemas do not match their Python scripts

- **Files:** `argus-workers/tools/definitions/playwright-xss.yaml`, `playwright-bola.yaml`, `playwright-privesc.yaml`; `argus-workers/tools/scripts/playwright_xss.py`, `playwright_bola.py`, `playwright_privesc.py`
- **Issue:** The YAML schemas expose `--username`, `--password`, `--form-page`, `--payload`, etc. The scripts accept only `--creds-file` and read credentials from a JSON file.
- **Why it blocks autonomy:** `mcp_server.call_tool` builds `--username foo --password bar ...` from the schema; the script rejects them and exits. All three Playwright verification tools are broken end-to-end.
- **Fix:** Either update the scripts to accept inline `--username`/`--password` parameters, or change the YAML schemas to a single `--creds-file` parameter and have `call_tool` serialize credentials to a temp JSON file.

### CRITICAL — `testssl` definition will hang waiting for interactive input

- **Files:** `argus-workers/tools/definitions/testssl.yaml`; `argus-workers/_generated_tools.py:946-960`
- **Issue:** `testssl` is defined with no CLI args. testssl.sh defaults to interactive ANSI output and waits for prompts/keyboard input in many environments. There is no `--batch`, `--fast`, or `--jsonfile` flag.
- **Why it blocks autonomy:** The tool hangs indefinitely, consuming the MCP/TypeScript timeout and producing no findings.
- **Fix:** Add default args such as `--batch`, `--fast`, and `--jsonfile <tmp>` and implement a parser.

### CRITICAL — `_generated_tools.py` misassigns repo-only tools to web scan phases

- **Files:** `argus-workers/_generated_tools.py:844-860` (semgrep), `:116-133` (bandit), `:425-441` (gitleaks), `:997-1014` (trufflehog), `:980-996` (trivy), `:647-664` (npm-audit), `:701-717` (pip-audit), `:442-458` (gosec), `:134-151` (brakeman), `:303-320` (eslint), `:893-909` (spotbugs), `:684-700` (phpcs)
- **Issue:** Repository-only tools are assigned to `scan` and/or `deep_scan` phases, while `tool_definitions.py` correctly assigns them to `repo_scan`.
- **Why it blocks autonomy:** The orchestrator/planner invokes repo tools against live web URLs, causing immediate failures that are silently logged. Critical code/dependency findings are never produced.
- **Fix:** Regenerate `_generated_tools.py` from the YAML definitions with correct phase mappings.

### CRITICAL — `testssl` gate compares a list literal string to URL prefixes

- **Files:** `argus-workers/_generated_tools.py:946-960`; `argus-workers/tool_definitions.py::evaluate_gate`
- **Issue:** `testssl` `requires=ToolRequires(target_scheme="['https']")`. `evaluate_gate` compares `target.startswith(req.target_scheme)`, so the string `"['https']"` is never a prefix of a real URL.
- **Why it blocks autonomy:** testssl is never selected even when the target uses HTTPS.
- **Fix:** Fix the generator to emit `target_scheme="https"` or update `evaluate_gate` to handle list-literal strings.

### CRITICAL — `FindingBuilder` rejects vulnerability types emitted by scanners

- **Files:** `argus-workers/tool_core/finding_builder.py:43-109`; `argus-workers/tools/web_scanner.py:1322`; `argus-workers/tools/api_scanner.py:303,314,336,371,392,444,493,501,516,536,553,610`; `argus-workers/tools/dual_auth_scanner.py:566,585,645`; `argus-workers/tools/attack_surface_mapper.py:91-98`
- **Issue:** `KNOWN_VULN_TYPES` is a closed allowlist. Multiple scanners emit types not in the allowlist:
  - `WebScanner.check_js_secrets()` emits `EXPOSED_SECRET`.
  - `api_scanner.py` emits `MISSING_API_SECURITY_HEADERS`, `WILDCARD_CORS_API`, `GRAPHQL_INTROSPECTION_ENABLED`, `GRAPHQL_DEPTH_LIMIT_MISSING`, `EXPOSED_OPENAPI_SPEC`, `VERBOSE_API_ERROR`, `MISSING_AUTHENTICATION`, `JWT_ALG_NONE`, `JWT_HMAC_ALGORITHM`, `JWT_PRIVILEGE_ESCALATION`, `JWT_LLM_DETECTED_WEAKNESS`, `WEAK_API_KEY`.
  - `dual_auth_scanner.py` emits `CONFIRMED_BOLA`, `POTENTIAL_BOLA`, `BOPLA_SENSITIVE_FIELDS`.
  - `attack_surface_mapper.py` emits `ATTACK_SURFACE`, `SUBDOMAIN`.
- **Why it blocks autonomy:** `FindingBuilder.add()` raises `ValueError` for unknown types, crashing the scanner on the first matching finding.
- **Fix:** Add all scanner-emitted types to `KNOWN_VULN_TYPES` or normalize them to existing equivalents.

### HIGH — `mcp_server.call_tool` discards findings-bearing non-zero exits

- **Files:** `argus-workers/mcp_server.py:624-651`
- **Issue:** `success = result.returncode == 0` and `dispatch()` is only called on success. stderr is never parsed. Many security tools (semgrep, bandit, gitleaks, dalfox, trivy, pip-audit) exit non-zero when findings exist or hosts are down.
- **Why it blocks autonomy:** Findings-bearing output is discarded. The MCP path silently loses results that `ToolRunner` explicitly preserves via `FINDINGS_EXIT_CODES`.
- **Fix:** Reuse `ToolRunner.FINDINGS_EXIT_CODES` (or share a registry), parse output even when exit code indicates findings, and combine stdout/stderr.

### HIGH — `nmap` YAML definition omits XML output

- **Files:** `argus-workers/tools/definitions/nmap.yaml`; `argus-workers/_generated_tools.py:630-646`; `argus-workers/tool_core/parser/parsers/nmap.py`
- **Issue:** Default args are `-Pn -T4 --top-ports 200`, producing human-readable terminal output. The parser expects `-oX`.
- **Why it blocks autonomy:** When invoked via the YAML/MCP path, nmap output is unstructured text and the parser returns no findings.
- **Fix:** Change default args to `-oX - -Pn -T4 --top-ports 200` and ensure the parser is registered.

### HIGH — Dependency-Check will hang or fail on NVD download

- **Files:** `argus-workers/tools/definitions/dependency_check.yaml`; `argus-workers/_generated_tools.py:252-268`
- **Issue:** Invoked with `--format JSON` but no `--noupdate` flag and no NVD API key. It attempts to download the NVD database on first run.
- **Why it blocks autonomy:** First invocation can hang for many minutes or fail with NVD rate limits.
- **Fix:** Add `--noupdate` by default, pre-seed the NVD cache in the worker image, or supply a configured NVD API key.

### HIGH — Cloud tools lack provider/auth parameters

- **Files:** `argus-workers/tools/definitions/cloud_enum.yaml`, `s3scanner.yaml`, `bucket_upload.yaml`
- **Issue:** Cloud tools accept only a target keyword/bucket name. No parameters for provider, AWS profile, region, GCP project, Azure subscription, or credentials.
- **Why it blocks autonomy:** The agent cannot authenticate to or scope cloud enumeration.
- **Fix:** Add optional provider, profile, region, and credential-role parameters.

### HIGH — `mcp_server` performs no scope validation before executing tools

- **Files:** `argus-workers/mcp_server.py:454-673`
- **Issue:** `call_tool` does not validate the target against the engagement's authorized scope.
- **Why it blocks autonomy:** A prompt-injected or misplanned MCP tool call can scan hosts outside the engagement scope.
- **Fix:** Inject `engagement_id` into `call_tool`, look up the engagement scope, and reject out-of-scope targets fail-closed.

### HIGH — `ToolRunner` synchronous path bypasses scope validation

- **Files:** `argus-workers/tools/tool_runner.py:379-663`
- **Issue:** `ToolRunner.run()` has no scope validation. Scope checks only exist in `AsyncToolRunner.run()` and some scanner `execute()` methods.
- **Why it blocks autonomy:** The legacy synchronous path can execute destructive tools against arbitrary targets.
- **Fix:** Move scope validation into `ToolRunner.run()` before dangerous-arg detection.

### HIGH — Orchestrator routes MCP calls around `ToolRunner` safety controls

- **Files:** `argus-workers/orchestrator_pkg/orchestrator.py:171-191`; `argus-workers/tools/mcp_bridge.py:77-83`
- **Issue:** `Orchestrator.mcp_run()` calls `mcp_bridge.call_via_mcp()` directly, invoking `mcp.call_tool()`. It never uses `call_via_runner()` or `ToolRunner`.
- **Why it blocks autonomy:** Circuit breaker, metrics, locked environment, output-size caps, and findings-exit-code handling are bypassed.
- **Fix:** Route `mcp_run()` through `MCPToolBridge.call_via_runner()`.

### MEDIUM — `dangerous_arg` check is literal substring matching

- **Files:** `argus-workers/tools/tool_runner.py:140-175`
- **Issue:** `is_dangerous()` uses literal substring matching (e.g., `rm -rf`, `DROP TABLE`) against the full command string.
- **Why it blocks autonomy:** Legitimate target URLs or payloads containing those substrings are blocked, causing false positives.
- **Fix:** Use positional/flag-aware validation.

### MEDIUM — Missing tools are silently skipped

- **Files:** `argus-workers/mcp_server.py:391-398`; `argus-workers/tools/mcp_bridge.py:54-70`
- **Issue:** Tools whose binary is not on PATH are skipped with only a warning log.
- **Why it blocks autonomy:** The planner sees a reduced catalog and assumes the missing capabilities are not needed.
- **Fix:** Surface missing tools as obstacles and optionally attempt installation.

---

## 2. LLM Agent, Safety, and Scope Control Defects

### CRITICAL — ReAct agent does not enforce engagement scope

- **Files:** `argus-workers/agent/react_agent.py:616-691`; `argus-workers/tools/scope_validator.py:21-284`
- **Issue:** `_validate_arguments()` only blocks private/loopback/link-local IPs and a short list of cloud metadata hostnames. It never validates the selected target against the engagement's authorized scope.
- **Why it blocks autonomy:** An LLM-driven loop can be tricked into scanning unauthorized domains/IPs.
- **Fix:** Call `ScopeValidator.is_in_scope(target)` for every target-bearing argument before `registry.call()`.

### CRITICAL — Mandatory coverage/stopping rules are only prompt-based

- **Files:** `argus-workers/agent/agent_prompts.py:385-401,403-423,294-310`; `argus-workers/agent/react_agent.py:562-563,719,877-879`
- **Issue:** Stopping rules (minimum tool counts, required scanners) are written only into system prompts. The code treats `__done__` from the LLM as an unconditional stop.
- **Why it blocks autonomy:** The LLM can ignore or be jailbroken out of prompt instructions and stop early.
- **Fix:** Maintain a programmatic `coverage_tracker`; only allow `__done__` when it is satisfied.

### CRITICAL — Session tokens and credentials leak into LLM context

- **Files:** `argus-workers/agent/agent_prompts.py:884-937`; `argus-workers/agent/react_agent.py:260-289,291-314`
- **Issue:** Raw tool output is inserted into the agent's conversational history. `_sanitize_for_llm()` only strips prompt-injection patterns; it does not redact `Authorization`, `Cookie`, `Set-Cookie`, API keys, tokens, or passwords.
- **Why it blocks autonomy:** Recovered credentials are forwarded to the third-party LLM provider.
- **Fix:** Add a secret-redaction pass before any observation enters the LLM context.

### CRITICAL — Login/register credentials are persisted in decision checkpoints and logs

- **Files:** `argus-workers/agent/react_agent.py:945-951,1110-1126`; `argus-workers/agent/auth_checkpoint.py:45-53`; `argus-workers/tool_definitions.py:534-567`
- **Issue:** `email`/`password` action arguments are stored verbatim in `DecisionCheckpoint`. Encryption only occurs if `AUTH_CHECKPOINT_KEY` is set; otherwise credentials are plaintext.
- **Why it blocks autonomy:** Autonomous account registration/login is high-risk; persisting credentials unencrypted makes leakage permanent.
- **Fix:** Treat auth fields as sensitive; never log them; encrypt checkpoints with a mandatory key.

### CRITICAL — `FindingAnalyzer` sends raw evidence to the LLM without scrubbing

- **Files:** `Argus-Tui/packages/opencode/src/argus/engagement/finding-analyzer.ts:61-92,105-108`
- **Issue:** `buildAnalysisPrompt()` concatenates `finding.description` and `evidence[].content` with only 500-character truncation. No PII, secret, or token redaction.
- **Why it blocks autonomy:** Vulnerability evidence often contains PII, session cookies, or application secrets.
- **Fix:** Scrub evidence for secrets/PII before prompt construction.

### CRITICAL — `LLMParserFallback` sends raw tool output to the LLM

- **Files:** `argus-workers/llm_parser_fallback.py:168-177`
- **Issue:** The fallback base64-encodes raw tool output and asks the LLM to decode it. Base64 is not a security boundary, and no redaction is applied.
- **Fix:** Run secret/PII redaction before base64 encoding.

### HIGH — Tool-selection output is not schema-validated

- **Files:** `argus-workers/agent/react_agent.py:560-576`; `argus-workers/agent/tool_registry.py:39-101`
- **Issue:** `_call_llm_for_action()` extracts `tool`, `arguments`, `reasoning` but only checks that the tool name exists. It does not validate argument types, required parameters, enums, or `ToolRequires` gates.
- **Fix:** Validate the action against the tool's parameter schema and reject malformed decisions with a retry.

### HIGH — Deterministic fallback ignores recon signals and scope

- **Files:** `argus-workers/agent/react_agent.py:584-614`; `argus-workers/tool_definitions.py:1240-1281`
- **Issue:** When the LLM fails, `_deterministic_plan()` picks the first untried tool and runs it with `target=task`. It does not check `ToolRequires` gates or scope.
- **Fix:** Make the fallback consult `evaluate_gate()` and scope validation; stop if no eligible tools remain.

### HIGH — `LLMService` fallback returns plausible-looking placeholder analysis

- **Files:** `argus-workers/llm_service.py:180-200`; `argus-workers/llm_synthesizer.py:62-69`
- **Issue:** `_fallback()` returns a dict with `executive_summary`, `risk_level`, etc., and includes `_fallback: True`. Downstream consumers may ignore the flag.
- **Fix:** Return a strongly typed failure object; require explicit handling of "LLM unavailable."

### HIGH — `IntentParser` prompt-injection defenses are bypassable

- **Files:** `argus-workers/intent_parser.py:72-147,167-219,275-280`
- **Issue:** Sanitization relies on a fixed regex list and partial leetspeak normalization. No structured system/user separation, injection classifiers, or strict output constraints.
- **Fix:** Use strict JSON-schema validation with enum restrictions and validate `target_url` against scope.

### HIGH — No confidence scoring or calibration on LLM outputs

- **Files:** `argus-workers/agent/react_agent.py:549-554`; `argus-workers/llm_service.py:96-178`; `argus-workers/llm_synthesizer.py:30-71`; `Argus-Tui/packages/opencode/src/argus/engagement/finding-analyzer.ts:94-134`
- **Issue:** Tool-selection decisions, synthesis, and finding analysis are accepted without confidence scores, uncertainty estimates, or consistency checks.
- **Fix:** Request a calibrated `confidence` field; reject decisions below a tunable threshold.

### HIGH — Context-window management is character-based and unsafe

- **Files:** `argus-workers/agent/agent_prompts.py:749-846,1000-1037`
- **Issue:** Budgets are enforced with character counts (`3400 * 4`) and simple slicing. No real token accounting.
- **Fix:** Use a real tokenizer to count tokens and truncate lowest-priority sections while preserving system prompts.

### HIGH — Scope validator defaults to warn mode with weak glob matching

- **Files:** `argus-workers/tools/scope_validator.py:161-217,220-284`
- **Issue:** `_match_glob()` uses `fnmatch` case-insensitively. Default `mode="warn"` logs a warning but returns `True` for out-of-scope targets.
- **Fix:** Default to `allowlist` mode; validate domains using canonical eTLD+1 parsing.

### HIGH — Custom rule engine executes unvalidated community rules

- **Files:** `argus-workers/custom_rules/engine.py:40-63,69-121`; `argus-workers/custom_rules/registry.py:43-80`; `argus-workers/custom_rules/validator.py:35-42`
- **Issue:** Rules are loaded without calling `RuleValidator`. The validator's dangerous-regex list is incomplete.
- **Fix:** Run every rule through `RuleValidator` before loading; add regex execution timeouts.

### HIGH — LLM rate limiting is per-provider/worker, not per-engagement

- **Files:** `argus-workers/llm_client.py:123-128,260-321`; `Argus-Tui/packages/opencode/src/argus/engagement/llm-client.ts:28-219`; `Argus-Tui/packages/opencode/src/argus/engagement/finding-analyzer.ts:105-108`
- **Issue:** Python `LLMClient` has a 60 req/min sliding window per provider (in-process unless Redis is configured). TypeScript `LlmClientImpl` and `FindingAnalyzer` have no rate limiting.
- **Fix:** Implement per-engagement token/call budget and a global cross-worker token bucket.

---

## 3. Concurrency & State Consistency Defects

### CRITICAL — Distributed lock is non-functional

- **Files:** `argus-workers/distributed_lock.py:105,171,245,262`
- **Issue:** `_with_reconnect` expects a method-name string, but every call site passes a bound Redis method (`self.redis_client.set`, `self.redis_client.eval`, etc.). `getattr(self.redis_client, <bound method>)` raises `TypeError`.
- **Why it blocks autonomy:** Engagements cannot be serialized. Multiple workers can mutate the same engagement simultaneously, and `task_context()` likely crashes on lock acquisition.
- **Fix:** Pass method-name strings: `_with_reconnect("set", ...)`, `_with_reconnect("eval", ...)`, etc.

### CRITICAL — Phase tasks are not idempotent

- **Files:** `argus-workers/tasks/recon.py:81`; `tasks/scan.py:101-105,195,286`; `tasks/analyze.py:47-55`; `tasks/repo_scan.py:118`
- **Issue:** Phase tasks always attempt their work. `run_scan` forces `transition("scanning")` even if the engagement is already `analyzing`, `reporting`, or `complete`.
- **Why it blocks autonomy:** Celery retries, late acks, or redeliveries re-run destructive work and create duplicate findings.
- **Fix:** At the top of each phase task, query DB state and return early if the engagement has already passed that phase or is terminal.

### CRITICAL — `WorkflowRunner` has no cross-run serialization

- **Files:** `Argus-Tui/packages/opencode/src/argus/workflow-runner.ts:152-411`
- **Issue:** `WorkflowRunner.run` operates on in-memory collections with no lock. `saveFindings` upserts one record at a time but the final call overwrites the whole finding set.
- **Why it blocks autonomy:** Two concurrent runs for the same engagement clobber each other's results.
- **Fix:** Acquire a distributed/file lock for the engagement and add optimistic-concurrency (`version`/`updated_at`) to the root row.

### CRITICAL — Per-engagement encryption migration is racy and can corrupt state

- **Files:** `Argus-Tui/packages/opencode/src/argus/engagement/store.ts:438-459,503-533,348-403`
- **Issue:** Migration encrypts the file, renames it, deletes WAL/SHM files, and only then updates `engagements.storage_version`. There is no lock and the operations are not atomic.
- **Why it blocks autonomy:** A crash between file encryption and root-DB update makes the engagement unopenable.
- **Fix:** Use a process-level lockfile, an atomic marker, and rollback logic.

### CRITICAL — Worker settings encryption key is ephemeral

- **Files:** `argus-workers/database/settings_repository.py:20-30,33-44`
- **Issue:** If `SETTINGS_ENCRYPTION_KEY` is absent, a random key is generated and stored only in `os.environ`. It is never persisted.
- **Why it blocks autonomy:** After process restart, stored API keys/LLM credentials cannot be decrypted.
- **Fix:** Require `SETTINGS_ENCRYPTION_KEY` at startup and source it from a sealed secret, not process env.

### HIGH — DB connection-pool timeout is not actually enforced

- **Files:** `argus-workers/database/connection.py:150-190,222-236`
- **Issue:** `get_connection` implements its own deadline but `psycopg2.pool.ThreadedConnectionPool.getconn()` blocks on an internal semaphore when exhausted.
- **Why it blocks autonomy:** Workers can hang indefinitely waiting for a connection, consuming Celery slots.
- **Fix:** Use a pool that supports acquisition timeouts or switch to `psycopg`/`sqlalchemy` with `pool_timeout`.

### HIGH — Celery worker launcher kills workers abruptly

- **Files:** `argus-workers/celery_worker_launcher.py:58-82`
- **Issue:** Receives `SIGTERM`/`SIGINT` and calls `proc.terminate()` followed by `proc.wait()`. No warm shutdown or ack semantics.
- **Why it blocks autonomy:** In-flight tasks are redelivered and re-executed from the beginning, duplicating destructive work.
- **Fix:** Send `SIGTERM` and wait for Celery warm shutdown before forcing exit.

### HIGH — `_failed_transition_done` flag leaks across task invocations

- **Files:** `argus-workers/celery_app.py:279,313`; `argus-workers/tasks/base.py:109,313`
- **Issue:** The flag is set as an instance attribute on the shared Celery task object and never cleared.
- **Why it blocks autonomy:** A subsequent task failure may skip the failure transition, leaving engagements stuck in non-terminal states.
- **Fix:** Reset the flag at the start of every task invocation or store it on the request object.

### HIGH — WebSocket event batch buffer is not thread-safe

- **Files:** `argus-workers/websocket_events.py:72-74,224-230,242-266`
- **Issue:** `_batch_buffer` is mutated without holding `_flush_lock`. Concurrent threads can append/resize/iterate it simultaneously.
- **Fix:** Protect all `_batch_buffer` accesses with `_flush_lock` or use a thread-safe queue per engagement.

### HIGH — Loop-budget counters are in-memory and not atomically persisted

- **Files:** `argus-workers/loop_budget_manager.py:64-79,107-153`; `argus-workers/runtime/engagement_state.py:259-261`
- **Issue:** `consume()` increments local counters; persistence is an upsert of local values, not an atomic increment.
- **Why it blocks autonomy:** Multiple workers can exceed `max_cycles` without the DB reflecting the true count.
- **Fix:** Persist budget inside the same DB transaction as the state transition using `UPDATE ... SET current_cycles = current_cycles + 1 ... RETURNING ...`.

### HIGH — `asset_discovery` task runs without the engagement lock

- **Files:** `argus-workers/tasks/asset_discovery.py:16-134`
- **Issue:** Does not use `task_context` or `DistributedLock`. Performs non-atomic read-modify-write on `assets` rows.
- **Fix:** Wrap in the same lock as other phase tasks or make upserts idempotent with `INSERT ... ON CONFLICT`.

### HIGH — DLQ replay can re-execute destructive tasks on completed engagements

- **Files:** `argus-workers/tasks/replay.py:16-44`
- **Issue:** `replay_dlq_task` re-sends the original task without checking whether the engagement is terminal.
- **Fix:** Verify engagement is non-terminal before replay; use a fresh task ID and idempotency token.

### HIGH — Checkpoints are not transactionally linked to state transitions

- **Files:** `argus-workers/checkpoint_manager.py:42-91`; `tasks/base.py`; `tasks/recon.py:103-119`; `tasks/scan.py:101-105`
- **Issue:** Checkpoints and state transitions commit in separate transactions.
- **Fix:** Pass the same connection/transaction into both so they commit atomically.

### MEDIUM — `WorkerCache` query key ignores parameter values

- **Files:** `argus-workers/cache.py:285-296`
- **Issue:** `_query_key` hashes only the SQL template, not the parameters. Two queries with the same SQL but different values collide.
- **Fix:** Include parameter values in the cache key or disable query-result caching until safe.

### MEDIUM — Cancellation flag has a TOCTOU race

- **Files:** `argus-workers/tasks/base.py:221-232`
- **Issue:** The task reads the Redis `cancel:engagement:{id}` key and immediately deletes it. A crash after deletion loses the intent.
- **Fix:** Keep the cancellation flag until the engagement reaches a terminal state or persist it in Postgres.

---

## 4. Testing, Deployment, and Operational Gaps

### HIGH — CI excludes DB/Redis/e2e tests

- **Files:** `.github/workflows/lint.yml:264-270,312-313`
- **Issue:** Python tests run with `pytest -m "not requires_db and not requires_redis and not e2e"`. The e2e job only runs `doctor` and unit tests, not an actual `assess` against fixture targets.
- **Fix:** Add a CI job that spins up Postgres + Redis and runs integration/e2e assessment tests.

### HIGH — Tests mock critical autonomy paths

- **Files:** `Argus-Tui/packages/opencode/test/argus/unit/z-mocked/verify.test.ts`; `z-mocked/evidence.test.ts`; `z-mocked/resume.test.ts`
- **Issue:** Verification, evidence, and resume tests rely on mocked browser engines, credential stores, and collectors. The only real resume test is skipped.
- **Fix:** Add integration tests exercising real browsers, real credential files, and full resume flows.

### HIGH — No chaos, failure-injection, soak, or latency tests

- **Files:** entire repo; `Argus-Tui/packages/opencode/script/bench-test-suite.ts:1-52`; `argus-workers/tests/README.md:189-196`
- **Issue:** No chaos tests, no long-running soak tests, no benchmark for autonomous decision latency.
- **Fix:** Add failure-injection tests, a multi-hour soak harness, and a decision-latency benchmark.

### HIGH — Outdated/vulnerable dependencies with no audit in CI

- **Files:** `argus-workers/requirements.txt:11,23,49,68`; `argus-workers/Dockerfile:42-53`; `Argus-Tui/packages/opencode/package.json:36-155`
- **Issue:** `python-nmap==0.7.1` is old; `psycopg2-binary` lags security patches; Go tools are pinned but not audited; no SBOM or dependency-vulnerability scan in CI.
- **Fix:** Run `pip-audit`/`npm audit` in CI, maintain lock files, add nightly dependency scan.

### HIGH — Hardcoded `localhost/127.0.0.1` defaults throughout worker stack

- **Files:** `argus-workers/config/redis.py:24`; `config/config_manager.py:21,23`; `health_monitor.py:21`; `secrets_manager.py:42,149,155`; `websocket_events.py:70`; `runtime/state_cache.py:43`; `di_container.py:133`; `tasks/base.py:167`; `tasks/scan.py:40`; `tasks/utils.py:124`; `runtime/concurrency.py:35`
- **Issue:** Dozens of production paths default to `localhost`/`127.0.0.1`.
- **Fix:** Require these URLs explicitly in non-development mode; fail fast instead of defaulting to localhost.

### MEDIUM — `Makefile` `dev-worker`/`test-backend` recipes mishandle venv activation

- **Files:** `Makefile:16,19,26,37`
- **Issue:** Guard/activation is parsed so the activation branch is part of the `||` right-hand side and only runs when the test fails.
- **Fix:** Wrap guard and activation in a subshell: `(test -f venv/bin/activate && . venv/bin/activate && celery ...) || { echo ...; exit 1; }`.

### MEDIUM — `start-argus.sh` assumes fixed directory layout and interactivity

- **Files:** `start-argus.sh:30-31,95-104,108-118,145-210`
- **Issue:** Hardcodes `Argus-Tui` and `Argus-Tui/packages/opencode` relative to `SCRIPT_DIR`; interactive prompt requires a TTY.
- **Fix:** Resolve paths via `git rev-parse --show-toplevel` or env vars; support fully non-interactive mode.

### MEDIUM — E2E script uses hardcoded `127.0.0.1` and a 60-second timeout

- **Files:** `scripts/e2e-test.sh:27,37,63`
- **Issue:** Hardcodes `http://127.0.0.1:3001/3002` and runs `assess` with `timeout 60`.
- **Fix:** Make target URLs configurable and use a realistic timeout with assertions on findings.

### MEDIUM — No schema migration runner beyond bind-mounted init scripts

- **Files:** `argus-workers/database/migrations/`
- **Issue:** Migrations are SQL files mounted into Postgres `initdb`; no tracked migration table or runner.
- **Fix:** Implement a migration runner with a `_migrations` tracking table.

### MEDIUM — Docker Compose binds sensitive services to loopback only

- **Files:** `docker-compose.yml:6,13,40,64`
- **Issue:** Postgres/Redis/Juice/DVWA bound to `127.0.0.1`; TLS commented out; no production compose file.
- **Fix:** Provide `docker-compose.prod.yml` with TLS, secrets, and no loopback binds.

### LOW — Many tests/docs use `example.com` and placeholder credentials

- **Files:** `_generated_tools.py:570,801`; `tool_core/sandbox.py:17`; `tool_core/result.py:80`; `intent_parser.py:227`; many test files
- **Issue:** Tests and examples use `https://example.com`, `admin/admin`, `password123`-like placeholders.
- **Fix:** Use fixture targets (e.g., Flask apps in `test_fixtures/`) in more tests.

---

# Part 3 — Updated Bottom Line

The deep-dive pass confirms that Argus is not merely "not fully autonomous" — it is **operationally fragile** in its current state. Several subsystems that would be exercised during an unattended run contain crash-level bugs:

1. **Tool definitions are miswired** (Playwright scripts reject YAML args, repo tools run against web targets, `testssl` never matches HTTPS, scanners crash on their own finding types).
2. **Safety controls are bypassable** (MCP has no scope validation, `ToolRunner` sync path skips scope, orchestrator routes around safety controls, LLM context leaks credentials).
3. **Distributed coordination is broken** (the Redis lock implementation raises `TypeError`, phase tasks are not idempotent, `WorkflowRunner` has no serialization, budget counters are not atomic).
4. **Deployment and test infrastructure do not support autonomy** (features disabled by default, manual secrets, CI skips DB/Redis/e2e, no chaos/soak tests, outdated dependencies unaudited).

A conservative, prioritized remediation order is:

1. Fix the distributed lock and make phase tasks idempotent.
2. Add an autonomous profile and programmatic approval policy.
3. Fix the Playwright/tool-definition mismatches and scanner finding-type crashes.
4. Enforce scope validation at every tool entry point.
5. Add secret/PII redaction before LLM prompts and checkpoint persistence.
6. Implement real dynamic replanning and wire verification into the pipeline.
7. Harden deployment (auto secrets, production compose, migration runner).
8. Expand CI to run DB/Redis/e2e tests, dependency audits, and chaos/soak harnesses.

Until these are in place, Argus cannot safely run unsupervised red-team engagements.

---

# Part 4 — Level 3 Findings: Security, Schema, Browser/Evidence Internals

This section records the most severe issues uncovered during a third, line-by-line pass focused on security vulnerabilities, database schema/runtime mismatches, browser stealth, evidence integrity, and reporting safety. These findings are concrete bugs and design flaws that would cause autonomous runs to crash, leak data, or produce untrustworthy results.

---

## 1. Security Vulnerabilities & Unsafe Defaults

### CRITICAL — Web scanner follows redirects without re-validating scope

- **Files:** `argus-workers/tools/web_scanner.py:120-132`, `158-169`
- **Issue:** `requests.get(..., allow_redirects=True)` lets a target redirect the scanner to internal/private URLs after the initial scope check. The scanner only validates the *original* URL.
- **Exploit scenario:** Attacker-controlled target returns `302 http://169.254.169.254/latest/meta-data/iam/security-credentials/`. The scanner follows the redirect and exfiltrates cloud metadata.
- **Why it blocks autonomy:** Allows autonomous scans to pivot into infrastructure outside the declared scope.
- **Fix:** Disable automatic redirects; if following redirects is required, re-run scope and private-IP checks on every hop.

### CRITICAL — Webhook dispatch is vulnerable to SSRF / DNS rebinding

- **Files:** `argus-workers/post_finding_hooks.py:150-172`
- **Issue:** `socket.getaddrinfo()` is used to validate the webhook hostname. If resolution fails, the function returns `True` (fail-open). Short-TTL DNS records can resolve to a public IP during validation and an internal IP at request time.
- **Exploit scenario:** Finding webhook leaks results to an internal service after validation passes.
- **Why it blocks autonomy:** Unattended autonomous runs can exfiltrate findings to attacker destinations.
- **Fix:** Resolve synchronously at request time; reject if resolution fails; enforce IP allowlist/blocklist on the resolved address before connecting.

### CRITICAL — `mcp_server` tool loader trusts YAML `command` field and only checks basename

- **Files:** `argus-workers/mcp_server.py:138-180`
- **Issue:** `base_cmd = command.split()[0].lower()`; only the basename is checked against a blocklist. Absolute paths such as `/usr/local/bin/bash` bypass it. New YAML files in the workflow directory are loaded without signature validation.
- **Why it blocks autonomy:** A compromised planner or writable workflow directory can inject new shell tools that the MCP server permits.
- **Fix:** Maintain a strict allow-list of absolute paths to approved tool binaries and validate YAML file signatures/hashes.

### CRITICAL — Tool execution exposes the full parent environment to child processes

- **Files:** `argus-workers/tools/tool_runner.py:323-349`; `argus-workers/mcp_server.py:53-76`
- **Issue:** `_locked_env()` copies `os.environ` and strips only a small `BLOCKED_ENV_VARS` set. Cloud tokens, CI secrets, internal hostnames, and `ARGUS_*` config remain accessible.
- **Why it blocks autonomy:** Secrets leak to child processes and any tool that dumps its environment.
- **Fix:** Start with a minimal, explicitly allow-listed environment rather than copying the parent env.

### HIGH — Subprocess safety relies on an easily bypassed substring blocklist

- **Files:** `argus-workers/tools/tool_runner.py:47-111`
- **Issue:** `is_dangerous()` checks whole args against a small set of substrings (`rm -rf`, `;`, `&&`, `|`, `` ` ``, `$(`). It does not block `rm -r /`, `python3`, `sh -c`, `dash`, `perl -e`, `--eval=...`, or metacharacters embedded inside larger args.
- **Why it blocks autonomy:** Weak guardrail gives a false sense of safety; destructive commands can slip through.
- **Fix:** Replace blocklist with strict JSON schemas per tool; validate each argument with regex or enum.

### HIGH — Auth manager validates only the first IPv4 record and ignores IPv6 / redirect chains

- **Files:** `argus-workers/tools/auth_manager.py:160-201`
- **Issue:** `socket.gethostbyname()` returns only one IPv4 address. AAAA records and additional A records are ignored. A hostname whose first A record is public but later records or redirect targets are private can bypass the guard.
- **Why it blocks autonomy:** Scope enforcement can be evaded during autonomous credential-based testing.
- **Fix:** Use `socket.getaddrinfo` to enumerate all addresses; block if any resolve to private/loopback/link-local; re-validate every redirect hop.

### HIGH — CLI/TUI no-args entry point forces interactive TUI launch

- **Files:** `Argus-Tui/packages/opencode/src/argus/index.ts:27-63`
- **Issue:** Running `argus` without arguments spawns the OpenCode TUI. In a headless context this hangs or crashes.
- **Why it blocks autonomy:** The CLI cannot be used non-interactively without arguments.
- **Fix:** Provide a non-interactive default (print help and exit); keep TUI launch behind an explicit `argus tui` command.

### HIGH — `ConfigLoader.loadFrom()` accepts arbitrary paths and silently fails

- **Files:** `Argus-Tui/packages/opencode/src/argus/config/loader.ts:92-112`
- **Issue:** No path allowlist. A caller can pass `/etc/shadow`, `../../.env`, etc. Read/parse errors silently return `{}`.
- **Why it blocks autonomy:** Autonomous or attacker-influenced code can exfiltrate arbitrary local files via config loading.
- **Fix:** Restrict paths to a known config directory; reject symlinks/relative escapes; return an error on failure.

### HIGH — `ToolConfig` loads tool paths from YAML without validation

- **Files:** `Argus-Tui/packages/opencode/src/argus/config/tool-config.ts:64-66`
- **Issue:** `settings.paths` is a `Record<string, string>` returned verbatim. If passed to `exec`, these become command-injection vectors.
- **Fix:** Validate paths against an allowlist of installed tools and reject shell metacharacters.

### MEDIUM — Temp sandbox directories may persist after crash

- **Files:** `argus-workers/tools/tool_runner.py:155-173`
- **Issue:** Cleanup is registered via `atexit`; if the worker is killed (`SIGKILL`) or crashes, scratch files remain in `/tmp`.
- **Fix:** Create temp dirs inside a single root per engagement and schedule periodic cleanup.

### MEDIUM — Async tool runner uses predictable temp directory names

- **Files:** `argus-workers/tool_core/sandbox.py:104-115`
- **Issue:** Temp dirs are derived only from `target` and `tool_name` hashes, with no random component. Concurrent scans collide; an attacker can pre-create the directory.
- **Fix:** Use `tempfile.mkdtemp` with a random suffix and include the engagement ID.

### MEDIUM — Evidence viewer has TOCTOU path-traversal window

- **Files:** `Argus-Tui/packages/opencode/src/argus/tui/routes/evidence-viewer.tsx:80-99`
- **Issue:** `realpathSync` resolves symlinks, but a symlink can be swapped between the check and the subsequent read.
- **Fix:** Open directories with `O_NOFOLLOW`, use `lstat` and reject symlinks, or copy evidence to a trusted staging area.

---

## 2. Database Schema / Runtime Mismatches

### CRITICAL — `EngagementRepository.create()` references columns that do not exist

- **Files:** `argus-workers/database/repositories/engagement_repository.py:38-60`; `argus-workers/database/init/01-schema.sql:8-20`; `argus-workers/database/migrations/001_base_schema.sql:9-22`
- **Issue:** Inserts into `target_url`, `authorization_proof`, `authorized_scope`, `created_by` and joins a `users` table. The shipped schema only defines `target`, `status`, `workflow`, `workflow_version`, timestamps, and `metadata`. No `users` table exists.
- **Why it blocks autonomy:** Creating an engagement crashes at runtime; the autonomous lifecycle cannot start against a fresh database.
- **Fix:** Align the repository with the schema or add the missing migration for `target_url`, `authorization_proof`, `authorized_scope`, `created_by`, and `users`.

### CRITICAL — `SettingsRepository` queries non-existent `user_settings` columns

- **Files:** `argus-workers/database/settings_repository.py:67-69,89-91,116-119`; `argus-workers/database/init/01-schema.sql:59-66`
- **Issue:** SQL references `user_email`, `key`, `value`. The actual table has `user_id` (TEXT UNIQUE) and `settings` (JSONB).
- **Why it blocks autonomy:** API-key retrieval fails, breaking LLM/scan worker startup.
- **Fix:** Update SQL to query `settings->>'openai_api_key'` etc., or add a migration to the expected key/value schema.

### CRITICAL — `FindingRepository` references columns absent from migrations

- **Files:** `argus-workers/database/repositories/finding_repository.py:147-158,271-369,523-541`
- **Issue:** Inserts/updates `cvss_score`, `owasp_category`, `cwe_id`, `evidence_strength`, `tool_agreement_level`, `fp_likelihood`, `verified`, `last_seen_at`. No migration creates most of these columns.
- **Why it blocks autonomy:** Every finding insert/update raises `UndefinedColumn`, halting autonomous scanning.
- **Fix:** Add a migration creating all missing finding columns, or remove them from repository SQL.

### CRITICAL — `tool_metrics` table is used but never created

- **Files:** `argus-workers/database/migrations/010_add_tool_metrics_engagement.sql:4`; `argus-workers/database/repositories/tool_metrics_repository.py:43-49`
- **Issue:** Migration 010 alters `tool_metrics` to add `engagement_id`, but no migration creates the table.
- **Fix:** Add migration `00x_add_tool_metrics_table.sql` before migration 010.

### HIGH — Row-level security is not enforced by most repositories

- **Files:** `argus-workers/database/repositories/agent_decision_repository.py:67-68,107-108,138-139`; `report_repository.py`; `finding_repository.py`; `argus-workers/database/migrations/008_add_tenant_isolation.sql:30-59`
- **Issue:** Repositories call `db_cursor()` without passing `org_id`. RLS policies use `current_setting('app.current_org_id', true)`, which returns `NULL` when not set. Only `engagements`, `findings`, and `audit_logs` have RLS policies.
- **Why it blocks autonomy:** A multi-tenant autonomous agent can read/write across organizations.
- **Fix:** Require `org_id` for all tenant-scoped queries; add RLS policies to all tenant tables.

### HIGH — `target_profiles` table is referenced but not created

- **Files:** `argus-workers/database/repositories/target_profile_repository.py:119-219`
- **Issue:** Upserts into `target_profiles` with `(org_id, target_domain)` conflict target, but no migration creates the table.
- **Fix:** Add migration creating `target_profiles` with expected columns and unique constraint.

---

## 3. Credential & Secret Handling

### CRITICAL — Auth checkpoint password stored plaintext when `AUTH_CHECKPOINT_KEY` is unset

- **Files:** `argus-workers/agent/auth_checkpoint.py:45-54`
- **Issue:** Encryption only runs if `AUTH_CHECKPOINT_KEY` is set. If unset, the password is written verbatim into `agent_decision_log.arguments`. The exception handler only logs a warning.
- **Why it blocks autonomy:** Autonomous retries rely on auth checkpoints; missing env var silently leaks credentials.
- **Fix:** Abort persistence or use a mandatory key; fail at startup if the key is missing.

### CRITICAL — Auth checkpoint serializes full AuthContext (tokens, cookies, CSRF) in plaintext

- **Files:** `argus-workers/agent/auth_checkpoint.py:40-46,144`
- **Issue:** `ctx.to_dict()` includes `cookie_string`, `authorization`, and `csrf_token`. Only `password` is conditionally encrypted.
- **Fix:** Encrypt the entire serialized checkpoint payload with an authenticated cipher and a mandatory key.

### CRITICAL — TUI credential store keeps plaintext passwords in JSON

- **Files:** `Argus-Tui/packages/opencode/src/argus/engagement/credentials.ts:1-85`
- **Issue:** `CredentialStore.save()` writes `{ roles: { admin: { username, password } } }` as plaintext JSON with `chmod 0o600`. No OS keychain, no encryption.
- **Fix:** Integrate with OS keychain/secret service or encrypt the file with a key from secure storage.

### CRITICAL — `AuthConfig` holds all secrets in plaintext dataclass fields

- **Files:** `argus-workers/tools/auth_manager.py:26-52`
- **Issue:** `password`, `cookie`, `token`, `api_key`, `oauth_client_secret`, `saml_assertion` are stored as plain strings with no secure lifecycle.
- **Fix:** Use secure string wrappers with explicit zeroing, or delegate to a keyring/secret manager.

### HIGH — Browser auth extracts and persists localStorage tokens without validation

- **Files:** `argus-workers/tools/auth_manager.py:516-557`
- **Issue:** `_try_extract_browser_session()` pulls `token`, `access_token`, `refresh_token` from `localStorage` and attaches them as `Authorization: Bearer`. No validation of audience, issuer, or expiry.
- **Fix:** Validate token claims against the target origin and scope; store tokens encrypted.

### HIGH — `SettingsRepository` auto-generates an ephemeral encryption key

- **Files:** `argus-workers/database/settings_repository.py:20-30`
- **Issue:** If `SETTINGS_ENCRYPTION_KEY` is absent, a random key is generated and stored only in `os.environ`. The next process gets a different key; decryption failures are silently swallowed.
- **Fix:** Require a stable key from a secret manager at startup; remove fallback key generation.

---

## 4. Browser Automation & Verification

### CRITICAL — Playwright launch/context lacks stealth/evasion controls

- **Files:** `Argus-Tui/packages/opencode/src/argus/browser/engine.ts:17-32`
- **Issue:** Stock Playwright fingerprints; no `--disable-blink-features=AutomationControlled`, no viewport/user-agent/locale override, no plugin/JS-heap evasion.
- **Why it blocks autonomy:** Bot-detection (Cloudflare, DataDome, PerimeterX) blocks or serves captcha/interstitial pages.
- **Fix:** Add a stealth context profile and accept UA/viewport/locale/proxy config.

### CRITICAL — Login helper uses brittle hardcoded selectors

- **Files:** `Argus-Tui/packages/opencode/src/argus/browser/login.ts:8-45`
- **Issue:** Detects login forms by grepping raw HTML with regexes, then selects first text/password/submit inputs. Ignores MFA/CAPTCHA/SSO/OAuth/modal/dynamically rendered forms.
- **Fix:** Use Playwright locators by role/label/placeholder; support configured selectors; detect MFA/CAPTCHA and pause/notify; support cookie/token injection.

### HIGH — BOLA verifier reports BOLA when both users can access the same shared resource

- **Files:** `Argus-Tui/packages/opencode/src/argus/browser/verifiers/bola.ts:50-73`
- **Issue:** Both users hit the **same** `resourceUrl`. It never swaps object IDs between users.
- **Fix:** Supply per-user object IDs and verify cross-user denial.

### HIGH — XSS verifier detects execution by grepping `innerHTML` for hardcoded markers

- **Files:** `Argus-Tui/packages/opencode/src/argus/browser/verifiers/xss.ts:89-106`
- **Issue:** Searches `innerHTML` for `<script>`, `alert(`, `javascript:`. Does not listen for actual JS execution, does not handle DOM-based contexts, and injects the same payload into every visible form field.
- **Fix:** Confirm XSS with `page.on('dialog')`, `page.on('pageerror')`, or callback payload; support context-aware payloads.

### HIGH — `VerificationRunner` swallows all errors and returns empty evidence

- **Files:** `Argus-Tui/packages/opencode/src/argus/browser/verifiers/runner.ts:27-52`
- **Issue:** Any exception returns `passed: false, confidence: INFORMATIONAL, evidence: []`. Cleanup is best-effort.
- **Fix:** Return distinct error states, preserve partial evidence/logs, and ensure cleanup always runs.

### HIGH — `ChainedScenario` passes if any stage passes

- **Files:** `Argus-Tui/packages/opencode/src/argus/browser/verifiers/chained-scenario.ts:76-87`
- **Issue:** `passed: anyPassed`. A multi-step exploit chain is reported successful even if later required stages fail.
- **Fix:** Require all stages to pass for chain success; report chain break point on failure.

---

## 5. Evidence Integrity, Encryption & Storage

### CRITICAL — Evidence `packageHash` is left empty by every verifier

- **Files:** `browser/verifiers/priv-esc.ts:147-153`; `browser/verifiers/bola.ts:95-105`; `browser/verifiers/xss.ts:162-168`; `browser/verifiers/chained-scenario.ts:117-124`
- **Issue:** Each verifier returns `EvidencePackage` with `packageHash: ""`.
- **Why it blocks autonomy:** Findings have no verifiable integrity linkage to screenshots/requests.
- **Fix:** Compute the package hash and bind actual stored artifact references before returning.

### CRITICAL — `verifyPackage()` permits path traversal via `artifact.path`

- **Files:** `Argus-Tui/packages/opencode/src/argus/evidence/integrity.ts:66-67`
- **Issue:** `join(baseDir, engagementId, "artifacts", packageId, artifact.path)` with no validation of `artifact.path`. A manifest entry of `"../.../etc/passwd"` escapes the evidence directory.
- **Fix:** Resolve the path and ensure it is strictly inside the package directory; reject `..` and absolute paths.

### CRITICAL — Evidence collector silently falls back to plaintext when master key is not cached

- **Files:** `Argus-Tui/packages/opencode/src/argus/evidence/collector.ts:54-56,178-184,205-211,231-235`
- **Issue:** `_isEncrypted()` is true only if `encryptionEngagementId` is set **and** `EncryptionManager.getCachedMasterKey()` returns non-null. If the 5-minute TTL expires, evidence is written as plaintext without warning.
- **Fix:** Throw when encryption is requested but the master key is unavailable; never silently downgrade.

### HIGH — Package hash is not signed/tamper-evident

- **Files:** `Argus-Tui/packages/opencode/src/argus/evidence/hash.ts:13-28`
- **Issue:** `computePackageHash` is a plain SHA-256 over sorted manifest + artifact hashes. An attacker with filesystem access can modify artifacts and recompute the hash.
- **Fix:** Sign the package hash with an HMAC derived from the master key or store it in the encrypted engagement DB.

### HIGH — `StoragePaths` accepts arbitrary/relative base paths without containment check

- **Files:** `Argus-Tui/packages/opencode/src/argus/storage/paths.ts:37-59,68-88`
- **Issue:** `ARGUS_DATA_DIR` or `storage.base_path` is used as-is. Relative paths resolve from `PROJECT_ROOT`; no check confines data under a trusted root.
- **Fix:** Require absolute paths, resolve and verify the directory is within an allowed parent, and reject traversal.

### MEDIUM — Encrypted DB temp file is not securely wiped

- **Files:** `Argus-Tui/packages/opencode/src/argus/storage/encrypted-db.ts:184,293-296`
- **Issue:** Decrypted DB is written to a temp file with `0o600` but removed with `rmSync`, which does not overwrite data.
- **Fix:** Overwrite temp files before deletion or use an in-memory/RAM tmpfs location.

### MEDIUM — Evidence directories and plaintext files use default permissions

- **Files:** `Argus-Tui/packages/opencode/src/argus/evidence/collector.ts:65-66,172,183,210,236`; `evidence/store.ts:20-22`
- **Issue:** `mkdir({ recursive: true })` and `writeFile()` use default `umask` permissions.
- **Fix:** Create directories with `0o700` and plaintext files with `0o600`.

---

## 6. Reporting & AI-Generated Artifacts

### HIGH — Worker HTML report generator inserts values without escaping

- **Files:** `argus-workers/reporting/html_report.py:269-318`; `argus-workers/templates/compliance/*.html`
- **Issue:** Severity/status strings are placed directly into HTML class attributes and text nodes. `_escape()` is not applied to severity values. If source finding data are attacker-controlled or LLM-generated, this is an XSS/script-injection vector when Jinja autoescape is disabled.
- **Fix:** Apply HTML escaping to all inserted values, including class names; whitelist allowed severity/status tokens.

### HIGH — LLM report generator forwards raw findings/engagement context without validation

- **Files:** `argus-workers/llm_report_generator.py:44-58`
- **Issue:** `build_report_prompt` receives full `synthesis`, `scored_findings`, and `engagement` objects; the JSON result is used directly.
- **Fix:** Constrain the LLM to a strict schema, validate every returned field, and redact sensitive evidence before the prompt.

### HIGH — AI explainer leaks finding endpoints/types to the LLM and has weak verification

- **Files:** `argus-workers/ai_explainer.py:177-246,248-291,293-338`
- **Issue:** Sanitized clusters still include endpoint, vulnerability type, and severity; `_verify_explanation` only checks for invented CVEs.
- **Fix:** Provide a local/offline model option; validate explanations against input cluster fields and forbid changes to severity/confidence/type.

### HIGH — PoC generator auto-weaponizes findings and emits unvalidated code

- **Files:** `argus-workers/poc_generator.py:189-239,241-288`
- **Issue:** Evidence is partially redacted then sent to the LLM; returned PoC JSON is not syntax-checked, sandboxed, or safety-reviewed. It can generate destructive curl payloads or SQLi that drops data.
- **Fix:** Validate PoC syntax, restrict to read-only/reproduction commands, run in a sandbox, and require approval for destructive actions.

### HIGH — Chain exploit generator builds weaponized scripts with weak redaction

- **Files:** `argus-workers/chain_exploit_generator.py:55-79,279-341`
- **Issue:** Redaction regex covers fewer patterns than the PoC generator; forwards evidence and existing PoCs to the LLM; returns a 10,000-char script with no validation.
- **Fix:** Apply strict redaction, validate each script step, and sandbox execution.

### HIGH — Scan diff engine marks findings "fixed" without retesting

- **Files:** `argus-workers/scan_diff_engine.py:359-378,416-472`
- **Issue:** A finding is "fixed" if its fingerprint is absent from the current scan. Scan failures, auth errors, or endpoint changes are interpreted as remediation.
- **Fix:** Require a positive retest (or manual confirmation) before marking fixed; track scan reliability state.

---

## 7. CVSS / Compliance Scoring

### HIGH — CVSS score is a product of arbitrary multipliers, not a real CVSS vector

- **Files:** `argus-workers/cvss_calculator.py:96-133`
- **Issue:** `estimate_cvss()` computes `base * severity_multiplier * evidence_adjustment`. This is not a valid CVSS v3.1 calculation.
- **Why it blocks autonomy:** Autonomous severity triage and reporting are inconsistent and un-auditable.
- **Fix:** Compute real CVSS v3.1 base vectors for each finding type, or rename the field to `Risk Score`.

### HIGH — Compliance reporting is checklist-only and misleading

- **Files:** `argus-workers/compliance_reporting.py:330-345,32-58,846-873`
- **Issue:** PCI DSS checklist is a hardcoded subset of 14 items (PCI DSS 4.0 has 400+). A clean scan marks these 14 as “compliant.” Findings have no audit trail or evidence linkage.
- **Fix:** Remove pass/fail scoring unless mapped to actual tested controls; link each compliance finding to an evidence package hash and reviewer attestation.

---

# Part 5 — Final Summary & Prioritized Remediation

The three review passes confirm that Argus is **not only architecturally short of full autonomy but also operationally fragile and, in several areas, insecure by default**. Before it can safely run unsupervised red-team engagements, the following must be true:

1. **The code that runs must match the database schema.** Right now, core repositories reference columns and tables that do not exist in the shipped migrations; fresh databases cannot create engagements or save findings.
2. **Credentials and sessions must never be plaintext.** Auth checkpoints, TUI credential store, and settings repository all have plaintext or optional-encryption paths.
3. **Scope and safety must be enforced in code, not just prompts.** Redirects, MCP tools, webhook dispatch, and agent argument validation all have bypass paths.
4. **Distributed coordination must actually work.** The Redis lock implementation is broken, phase tasks are not idempotent, and `WorkflowRunner` has no cross-run serialization.
5. **Evidence must be tamper-evident and complete.** Empty package hashes, path traversal in integrity verification, silent plaintext fallback, and missing HAR/video all undermine forensic trust.
6. **Tool definitions and scanners must not crash themselves.** Closed finding-type allowlists, YAML/script mismatches, and missing parsers cause autonomous runs to fail silently.
7. **Deployment and CI must support unattended operation.** Features are off by default, secrets require manual setup, and CI skips the tests that matter for autonomy.

### Immediate priority order (first 30 days)

1. Fix schema/runtime mismatches (engagements, findings, settings, tool_metrics, target_profiles).
2. Fix the broken distributed lock and make phase tasks idempotent.
3. Implement mandatory encryption for auth checkpoints and TUI credential store.
4. Enforce scope validation on redirects, MCP `call_tool`, webhook dispatch, and agent argument selection.
5. Fix `FindingBuilder` to accept all scanner-emitted types and regenerate `_generated_tools.py`.
6. Add an autonomous profile that enables required feature flags and a programmatic approval policy.
7. Replace the no-op `_replan()` with real LLM/rule-based replanning.

Until these are completed, Argus should be treated as a **human-supervised, experimental scanner orchestrator**, not a production-ready autonomous red-team platform.
