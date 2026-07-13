# Session Progress — July 13, 2026

## Work Completed This Session (5 items)

### 1. ✅ LLM Suggestions Flow Through `planner.replan()`
LLM-generated phase suggestions are no longer created inline. They now flow through `planner.replan()`, which means dedup, chain merging, and budget tracking all work correctly.

### 2. ✅ Independent LLM + Rule Budgets
**`Argus-Tui/packages/opencode/src/argus/workflow-runner.ts`**, **`Argus-Tui/packages/opencode/src/argus/config/constants.ts`**
- LLM replanning has its own budget (`llmMaxReplans`) separate from deterministic rule replanning (`maxReplans`)
- Neither budget can starve the other — LLM can keep replanning even after rule budget is exhausted, and vice versa
- Configurable via `replan.llm_max_cycles` in `argus.config.yaml` and `ARGUS_LLM_MAX_REPLANS` env var

### 3. ✅ `ARGUS_LLM_MAX_REPLANS` Env Var
- **File:** `Argus-Tui/packages/opencode/src/argus/workflow-runner.ts`
- Reads `ARGUS_LLM_MAX_REPLANS` env var to set the LLM replanning budget
- Consistent with resume.ts — both use the same env var
- Falls back to `replan.llm_max_cycles` from config when env var is unset

### 4. ✅ 5 Unit Tests for `ARGUS_LLM_MAX_REPLANS` Fallback
**`Argus-Tui/packages/opencode/test/argus/unit/workflow-runner.test.ts`**
All 42 tests pass (5 new + 37 existing):

| Test | Verifies |
|------|----------|
| Sets `llmMaxReplans=5` when env var is set | `ARGUS_LLM_MAX_REPLANS=5` → `ctx.llmMaxReplans === 5` |
| `llmMaxReplans` is undefined when env var not set | Unset env var → undefined |
| Non-numeric env var results in undefined | `"abc"` → undefined |
| Negative env var results in undefined | `"-5"` → undefined |
| `ARGUS_LLM_MAX_REPLANS=0` passes through as 0 | `"0"` → 0 (disables LLM replanning) |

### 5. ✅ FindingBuilder Allowlist — Added ~30 Missing Scanner-Emitted Types
**`argus-workers/tool_core/finding_builder.py`**

Added all scanner-emitted types to `KNOWN_VULN_TYPES` organized by source:

| Source | Types Added |
|--------|------------|
| Web scanner | `POST_PARAMETER_REFLECTION` |
| WebSocket scanner | `WEBSOCKET_RATE_LIMITED` |
| Browser security operator | `FILE_UPLOAD_FORM`, `MISSING_CSRF_TOKEN`, `AUTH_DETECTED`, `MISSING_X_FRAME_OPTIONS`, `MISSING_X_CONTENT_TYPE_OPTIONS` |
| Infrastructure analyzer | `INFRA_SERVER_HEADER`, `INFRA_VIA_HEADER`, `INFRA_INFO_DISCLOSURE`, `INFRA_WEB_SERVER`, `TF_PUBLIC_ACL`, `TF_OPEN_SG`, `K8S_PRIVILEGED`, `K8S_HOST_NETWORK`, `DOCKER_LATEST_TAG`, `DOCKER_SECRETS_IN_ENV` |
| Threat intelligence | `DOMAIN_NOT_RESOLVED`, `CERTIFICATE` |
| Orchestration/status events | `ORCHESTRATION_PLAN`, `PHASE_STARTED`, `PHASE_COMPLETE`, `VERIFICATION_RECOMMENDED`, `ORCHESTRATION_COMPLETE`, `VERIFICATION_SUMMARY`, `ATTACK_PATHS`, `REPORT_GENERATED`, `ENGAGEMENT_ANALYTICS`, `EVIDENCE_SUMMARY`, `CWE_KNOWLEDGE`, `OWASP_MAPPING` |

**Previous behavior:** Unknown types triggered a warning log and normalized to `GENERIC_FINDING`, losing type identity in reports.

## Items Verified — Already Fixed (No Changes Needed)

### ✅ Distributed Lock `_with_reconnect()` Is Correct
**`argus-workers/distributed_lock.py`** — The audit claimed this was broken (passing bound Redis methods instead of method-name strings), but the code already handles both cases:
- `isinstance(name, str)` → uses `getattr(client, name)` for string method names
- `callable(name)` → calls bound methods directly
- All 8 call sites already pass string method names (`"set"`, `"get"`, `"exists"`, `"eval"`)

No change was needed.

### ✅ Secret/PII Redaction in `_sanitize_for_llm()` Is Comprehensive
**`argus-workers/agent/agent_prompts.py`** — The `_SECRET_REDACTION_PATTERNS` list already redacts:
- Bearer tokens (`Authorization: Bearer eyJ...`)
- Basic auth headers
- Cookies (`Cookie: session=abc123`)
- JWT tokens
- API keys (`sk-proj-*`, `sk-*`)
- AWS keys (`AKIA*`)
- GitHub tokens (`ghp_*`)
- Passwords in key=value pairs
- Private keys (RSA, EC, etc.)
- DB URLs with embedded credentials

All wired into `build_observation_summary()`, `react_agent.py`, `build_synthesis_prompt()`, and `build_report_prompt()`.

No change was needed.

---

## What's Still Blocking Full Autonomy

### 🔴 CRITICAL — Will Crash or Leak on Unattended Run

| # | Blocker | Status |
|---|---------|--------|
| 1 | **DB schema vs runtime mismatches** — `EngagementRepository.create()`, `FindingRepository`, `SettingsRepository` query columns that don't exist in shipped migrations. Fresh DB crashes on first engagement creation. | ❌ Not fixed |
| 2 | **Playwright YAML/script mismatches** — YAML exposes `--username`, `--password` but scripts accept only `--creds-file`. All 3 Playwright verification tools are broken end-to-end. | ❌ Not fixed |
| 3 | **Scope validation is bypassable** — Web scanner follows redirects without re-validating scope (SSRF into cloud metadata). MCP `call_tool` has no scope validation. `ToolRunner` sync path skips scope. ReAct agent doesn't validate targets against engagement scope. | ❌ Not fixed |
| 4 | **Credentials leak into LLM context** — Auth checkpoint passwords plaintext when `AUTH_CHECKPOINT_KEY` unset. Tool output with `Authorization`/`Cookie` headers forwarded to LLM providers without redaction. | ✅ Already fixed (see above) |

### 🟠 HIGH — Will Silently Produce Wrong Results

| # | Blocker | Status |
|---|---------|--------|
| 5 | **Post-exploitation never triggers automatically** — `PostExploitationOrchestrator` is fully implemented but never called by any automated pipeline. | ❌ Not fixed |
| 6 | **Verification pipeline isn't self-executing** — `run_verification()` marks findings but never launches Playwright. SSRF/LFI/JWT/Secrets verifiers exist but are dead code. | ❌ Not fixed |
| 7 | **Auth success detection is inverted** — `detectAuthSuccess()` returns `true` unless the page matches specific error regexes. Failed logins landing on generic pages count as success. | ❌ Not fixed |
| 8 | **No automated confidence promotion** — `ConfidenceEngine.promote()` is never called because verification never runs automatically. | ❌ Not fixed |
| 9 | **Evidence package hashes are empty** — Every verifier returns `packageHash: ""`. No integrity linkage between findings and screenshots/evidence. | ❌ Not fixed |
| 10 | **`_generated_tools.py` misassigns repo tools to web scan phases** — Semgrep, bandit, gitleaks invoked against live web URLs instead of repos → silent failures. | ❌ Not fixed |

### 🔵 INFRASTRUCTURE — Hard Dependencies

| # | Blocker | Status |
|---|---------|--------|
| 11 | ~60 external security tool binaries — nuclei, nmap, sqlmap, etc. must be pre-installed. `argus doctor` lists missing ones but assessment proceeds with zero tools. | ❌ Operational |
| 12 | Feature flags disabled by default — Every autonomy feature defaults to `false`. `ARGUS_AUTONOMOUS=1` profile exists but requires manual env var. | ❌ Config |
| 13 | No schema migration runner — Only bind-mounted init scripts. No tracked migration table, no rollback. | ❌ Not fixed |
| 14 | Credential store plaintext — `credentials.json` stores plaintext passwords with `chmod 0o600`. No OS keychain or encryption. | ❌ Not fixed |
| 15 | Browser engine lacks stealth — Minimal evasion. Bot detection (Cloudflare, DataDome) will block or serve CAPTCHA. MFA/CAPTCHA cannot be automated. | ❌ Not fixed |
| 16 | PostgreSQL + Redis + LLM API key — All required, no self-provisioning. | ❌ Infrastructure |

---

## Recommended Next Steps (Priority Order)

1. **Fix DB schema mismatches** — Align `EngagementRepository`, `FindingRepository`, `SettingsRepository` with actual migrations. This is the #1 crash-on-startup bug.
2. **Fix Playwright YAML/script mismatches** — Update scripts to accept inline `--username`/`--password` or change YAML to a single `--creds-file` parameter.
3. **Enforce scope at every tool entry point** — MCP `call_tool`, `ToolRunner.run()`, redirect following, ReAct agent argument validation.
4. **Wire verification into the automated pipeline** — After scan phase, auto-route HIGH/CRITICAL findings to verifiers. Call `ConfidenceEngine.promote()` when verification passes.
5. **Wire post-exploitation** — When attack graph detects chains or credentials are extracted, automatically trigger `PostExploitationOrchestrator`.
6. **Fix `_generated_tools.py` phase assignments** — Regenerate with correct `repo_scan` phase for repo-only tools.
7. **Fix auth success detection** — Replace absence-based heuristics with positive confirmation (logout button, session cookie changes, authenticated API probes).
