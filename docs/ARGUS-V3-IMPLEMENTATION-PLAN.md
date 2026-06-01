# ARGUS V3 Implementation Plan — Final (10 Iterations)

**Date:** 2026-06-01  
**Status:** Design complete, ready for implementation  
**Total:** ~815 lines new code, ~65 lines modifications, 0 lines refactored

---

## What This Plan Delivers

A **BOLA workflow engine** that runs as a first-class primitive inside the existing scan phase:

```
Create identity A → Create resource as A → Register identity B →
Switch to B's session → Replay A's captured request →
Analyze response → Generate findings
```

Built on top of the existing platform without rewriting a single working file.

---

## File Budget (Final, After 10 Iterations)

### New files (7)

| File | Lines | Purpose |
|---|---|---|
| `runtime/workflows/base.py` | ~50 | `Workflow` + `WorkflowStep` base classes, step checkpointing |
| `runtime/workflows/bola.py` | ~250 | `BolaWorkflow` class — 7 steps wired in sequence |
| `runtime/workflows/steps.py` | ~150 | `RegisterIdentityStep`, `CreateOrDiscoverStep`, `SwitchIdentityStep`, `RequestCaptureStep`, `ReplayStep`, `AnalyzeAuthorizationStep` |
| `runtime/workflows/resources.py` | ~60 | `ResourceCreationStrategy` — pluggable resource creation/discovery (V1: common POST patterns, V2: Playwright, V3: LLM) |
| `runtime/traffic/capture.py` | ~50 | `RequestCapture` — 30-line `Session.send` patch (V1; V2 = Playwright, V3 = mitmproxy) |
| `runtime/traffic/models.py` | ~20 | `CapturedRequest` schema — version-agnostic across all capture backends |
| `tests/` (multiple files) | ~300 | Unit, integration, E2E test files |
| **Total new** | **~880** | |

### Modified files (2)

| File | Change | Lines |
|---|---|---|
| `runtime/engagement_state.py` | Add `identities`, `sessions`, `resources`, `captured_requests`, `obstacles` fields + `add_obstacle()` + `to_dict_full()` | +50 |
| `orchestrator_pkg/scan.py:806-843` | Replace `DualAuthScanner` call with `BolaWorkflow` behind `_feature_enabled("bola_workflow")` flag | +15 |
| **Total modified** | | **+65** |

### Files with ZERO changes

`agent/tools/register_tool.py`, `agent/tools/login_tool.py`, `agent/form_discovery.py`,
`agent/auth_context.py`, `agent/auth_checkpoint.py`, `tools/dual_auth_scanner.py`,
`tools/auth_manager.py`, `orchestrator.py`, `phases.py`, `tasks/base.py`,
`tasks/scan.py`, `runtime/decision_checkpoint.py`, `state_machine.py`,
`pipeline_router.py`, `agent/agent_prompts.py`

---

## Iteration Results Summary

### Iteration 1 — Architecture & State Model

**Correction applied:** `EngagementState` at `runtime/engagement_state.py:63` IS production code (exported from `runtime/__init__.py:19`, used by `ExecutionEngine.execute()` at `runtime/execution_engine.py:138-149`). Not dead code. Extend it with 5 new fields instead of creating a new `OperationContext` god object.

**Gap found:** `to_dict()` at line 285-301 saves only counts (`findings_count`, `observations_count`, etc.) — not the actual data. Workflow needs `to_snapshot_dict()` (line 303-314) for full state. Added `to_dict_full()` method.

**Gap found:** `add_observation` at line 179-190 truncates to 2000 chars and caps at 50 entries. Workflow records via `record_tool_execution()` instead.

### Post-Review Refinement 1 — RequestCapture must be version-aware

**Concern (from review):** `requests.Session.send` patch only captures Python `requests`. Modern SPAs use Playwright/XHR/fetch. V1 is fine but V2/V3 must be explicitly planned.

**Existing Playwright infra at** `tools/_browser_scan_worker.py:69-75` already has `page.on('console', ...)` — the same `page.on('request', handler)` API is ready for V2.

**Fix:** Add a version-agnostic schema + docstring that commits to V2/V3:

```python
# runtime/traffic/models.py  (NEW)

@dataclass
class CapturedRequest:
    """Unified schema across all capture backends.
    V1: requests.Session.send patch (this PR)
    V2: Playwright page.on('request')  (infra exists at browser_scan_worker.py:69)
    V3: Mitmproxy dump file import
    """
    method: str
    url: str
    headers: dict
    body: str | None
    cookies: str = ""           # NEW — anti-replay headers, CSRF, nonce
    query_params: str = ""      # NEW — separate from URL for clean replay
    content_type: str = ""      # NEW — explicit CT for body encoding
    owner_identity_id: str
    captured_at: float = time.time()
    source: str = "session_patch"  # "session_patch" | "playwright" | "mitmproxy"
```

**Delta:** +1 file (`models.py`, ~20 lines), +docstring on `RequestCapture`.

### Post-Review Refinement 2 — Resource creation needs a strategy pattern

**Concern (from review):** POST to URL template works for controlled targets (crAPI, Juice Shop) but not real engagements — each app has a different resource creation flow.

**Fix:** Rename `CreateResourceStep` → `ResourceCreationStrategy`. V1 strategy tries common POST patterns and falls back to GET-based discovery (existing `_discover_owned_resources` at `dual_auth_scanner.py:286-348`). V2+ strategy can use LLM reasoning, browser automation, or manual script.

```python
# runtime/workflows/resources.py  (NEW ~60 lines)

class ResourceCreationStrategy:
    """Pluggable: how does the workflow create resources as identity X?
    V1: try POST /api/{type}/ with generic JSON body, fall back to GET discovery
    V2: Playwright form fill + submit
    V3: LLM-guided (agent reasons about the target's form)
    """
    def create_or_discover(self, identity, resource_type: str) -> list[str]:
        # Try create first (POST)
        # Fall back to discover (GET crawl — reuse dual_auth_scanner logic)
```

**The BolaWorkflow receives it as injected dependency:**
```python
workflow = BolaWorkflow(
    target=target,
    resource_strategy=ResourceCreationStrategy()  # injected, not hardcoded
)
```

**Delta:** +1 file (`resources.py`, ~60 lines), BolaWorkflow constructor takes `resource_strategy` parameter.

### Post-Review Refinement 3 — Obstacles must carry recovery metadata

**Concern (from review):** Obstacles are recorded, not solved. The data model should anticipate future recovery providers without building them now.

**Fix:** Add `recoverable: bool` and `recovery_paths: list[str]` to every Obstacle dict:

```python
Obstacle = {
    "type": str,                    # "email_verification_required"
    "detected_at": float,
    "source_tool": str,
    "confidence": float,
    "recoverable": bool,            # NEW — True if a recovery path exists
    "recovery_paths": list[str],    # NEW — ["try_login_anyway", "skip"]
    "metadata": dict,
}
```

**V1 recovery table:**

| Obstacle | Recoverable? | V1 paths | V2+ paths |
|---|---|---|---|
| `email_verification_required` | No | `["try_login_anyway"]` | EmailProvider |
| `captcha_detected` | No | `["skip_target"]` | CaptchaProvider |
| `2fa_required` | No | `["skip_auth"]` | OtpProvider |
| `rate_limited` | Yes | `["backoff_and_retry"]` | Scheduler |
| `account_locked` | No | `["skip_auth"]` | Recovery flow |
| `email_exists` | Yes | `["regenerate_email"]` | Multi-domain |

**Delta:** ~5 lines added to the Obstacle dict in each step wrapper.

### Post-Review Refinement 4 — WorkflowResult contract

**Concern:** `Workflow.execute()` returns a loose dict. When `BolaWorkflow`, `IdorWorkflow`, `PrivilegeEscWorkflow` all exist, the orchestrator needs a uniform return type.

**Fix:** Define a `WorkflowResult` dataclass that every workflow returns:

```python
# runtime/workflows/base.py

@dataclass
class WorkflowResult:
    """Uniform result contract for ALL workflow types.
    Orchestrator dispatches on this — it doesn't inspect workflow internals.
    """
    success: bool
    findings_created: int
    obstacles_encountered: int
    identities_created: int
    resources_created: int
    requests_captured: int
    metadata: dict                         # workflow-specific (e.g. resource types tested)

    @classmethod
    def from_state(cls, state: EngagementState) -> "WorkflowResult":
        return cls(
            success=len(state.findings) > 0,
            findings_created=len(state.findings),
            obstacles_encountered=len(state.obstacles),
            identities_created=len(state.identities),
            resources_created=len(state.resources),
            requests_captured=len(state.captured_requests),
            metadata={
                "engagement_id": state.engagement_id,
                "current_phase": state.current_phase,
                "state_version": state.state_version,
            },
        )
```

**Then every `workflow.execute(state)` ends with:**
```python
return WorkflowResult.from_state(state)
```

**The orchestrator reads one field to decide what to do next:**
```python
if result.success:
    emit_finding_rt(...)
else:
    # result.obstacles_encountered > 0 — partial coverage, proceed anyway
```

**Delta:** ~20 lines added to `runtime/workflows/base.py`. No behavioral change — `WorkflowResult.from_state()` is a constructor, not a run path.

### Post-Review Refinement 5 — Anti-replay risk acknowledgement

**Concern (from review):** V1 `ReplayStep` replays captured frames without refreshing CSRF tokens, anti-replay headers, or request signatures. Targets that validate these will reject the replayed request — the BOLA test produces a false negative.

**Risk assessment:** Real but acceptable for V1. Three scenarios:

| Target behavior | Replay result | Workflow outcome |
|---|---|---|
| No CSRF / no anti-replay | Normal response | CONFIRMED_BOLA or POTENTIAL_BOLA (correct) |
| Per-request CSRF token | 403 Forbidden | `Obstacle("replay_rejected", recoverable=False)` — recorded, workflow continues |
| Request signature (HMAC, JWT binding) | 403 or silent authz | `Obstacle("replay_rejected")` — workflow continues |

**No code change needed.** The `Obstacle` data model (Refinement 3) already has `recoverable: bool` and `recovery_paths: list[str]`. V1 sets both to `False` and `["skip"]` for replay failures. V2+ can implement per-request CSRF token refresh or request re-signing.

**Delta:** 0 lines of code. Documented in the mitigation log.

### Iteration 2 — Celery Serialization & Cross-Task State

**Key insight:** The BolaWorkflow runs INSIDE a single Celery task (the scan task at `tasks/scan.py:15`, `soft_time_limit=2400`). Steps are in-memory; no cross-task serialization needed.

**Crash recovery:** Reuse existing `DecisionCheckpoint` at `runtime/decision_checkpoint.py:95-124` to checkpoint each step's result to `agent_decision_log`. On retry, `find_latest_checkpoint()` skips completed steps. `register_tool.py:209-213` handles `EMAIL_EXISTS` on re-run.

### Iteration 3 — Concurrency & Session Lifecycle

**Key insight:** The BolaWorkflow runs synchronously BEFORE the `ThreadPoolExecutor(max_workers=5)` at `orchestrator_pkg/scan.py:684`. `DistributedLock` at `tasks/base.py:166` prevents concurrent engagement writes. No thread-safety issues.

**Missing:** Wire `BolaWorkflow` through `ExecutionEngine.execute()` at `runtime/execution_engine.py:138-149` for free step recording to `EngagementState.tool_history`.

### Iteration 4 — Detector Refactor / "No Refactoring"

**Key insight:** `run_register` and `run_login` return `(UnifiedToolResult, AuthContext)`. On `NONZERO_EXIT`, stdout contains JSON with `error_code`. The workflow wrapper parses this and converts to an obstacle — no changes needed to register_tool.py or login_tool.py.

**Zero lines changed in existing tools.** The entire detector-to-obstacle conversion lives in `steps.py` — ~40 lines of wrapper code.

### Iteration 5 — Failure Modes & Workflow Interruption

**Key insight:** `state_machine.py:41-50` has `"failed": []` — no transitions out of 'failed'. If the workflow lets an exception propagate, the engagement is dead.

**Fix:** `Workflow.execute()` catches all step exceptions. They become obstacles. The workflow never throws. `SoftTimeLimitExceeded` still terminates at the Celery level (caught at `tasks/base.py:202`).

### Iteration 6 — Test Strategy (Dedicated)

Three-layer architecture:
1. **Unit tests** (pure Python, all mocks): `test_request_capture.py`, `test_workflow_base.py`, `test_workflow_steps.py`, `test_bola_workflow.py`, `test_engagement_state_extensions.py`
2. **Integration tests** (real tool logic, mock HTTP): `test_workflow_checkpoint_recovery.py`, `test_request_capture_integration.py`
3. **E2E test** (real threaded HTTP server): `test_e2e_bola_workflow.py` — proves the full chain without network or infrastructure

### Iteration 7 — Observability, Logging, Debugging

Follow `DualAuthScanner`'s pattern at `dual_auth_scanner.py:168-228`:
- `ScanLogger` for structured phase logging (`slog.phase_header`, `slog.tool_start/complete`)
- `emit_tool_start/complete` for frontend SSE events
- `state._bump_version()` after each step for Redis persistence
- **Never log passwords or raw cookies.** Follow the pattern at line 181: `slog.info("User A authenticated")`.

### Iteration 8 — Migration & Incremental Rollout

5-step migration, each independently revertable:

| Step | Change | Feature flag |
|---|---|---|
| 1 | EngagementState extensions | None |
| 2 | `runtime/traffic/capture.py` | None |
| 3 | `runtime/workflows/` | None |
| 4 | Wire into scan.py | ✅ `_feature_enabled("bola_workflow", default=False)` |
| 5 | Remove flag, deprecate DualAuthScanner | Remove flag |

**Step 4 is the safety gate.** Deploy all code with the flag OFF. Flip ON for test engagements. If it breaks, `redis-cli DEL "feature_flag:bola_workflow"` restores legacy behavior.

### Iteration 9 — Cost, Performance, Caching

BolaWorkflow costs vs. DualAuthScanner:

| Resource | DualAuthScanner | BolaWorkflow | Acceptable? |
|---|---|---|---|
| HTTP requests | ~4 | ~7 | Yes — within 40min soft limit |
| DB writes | 0 | 7 × 500 bytes | Trivial |
| Redis writes | 0 | 7 × ~100 bytes | Trivial |
| Wall time | ~20s | ~40s | Noise in 2400s budget |

**Secrets must NOT be cached.** `to_dict_full()` must exclude `password`, `cookie_string`, and `authorization`.

---

## Final Architecture

```
tasks/scan.py (existing)
  └─ task_context(...)                          [DistributedLock + state machine]
      └─ Orchestrator.run_scan(job)             [existing dispatcher]
          └─ execute_scan_tools(...)            [existing: orchestrator_pkg/scan.py]
              ├─ [existing parallel tools]      [ThreadPoolExecutor]
              └─ bola_workflow (NEW)            [if dual_auth_config provided]
                  ├─ RegisterIdentityStep A     [wraps register_tool.run_register]
                   ├─ CreateOrDiscoverStep      [ResourceCreationStrategy V1: POST common patterns → GET fallback]
                  ├─ LoginIdentityStep B        [wraps login_tool.run_login]
                  ├─ RequestCaptureStep         [Session.send patch]
                  ├─ SwitchIdentityStep         [swap AuthContext]
                  ├─ ReplayStep                 [re-issue captured frame under new identity]
                  └─ AnalyzeAuthorizationStep   [reuses dual_auth_scanner BOLA logic]
                  
                  ↑ each step saves checkpoint to agent_decision_log
                  ↑ each step calls state._bump_version() → Redis cache
                  ↑ step exceptions become obstacles, not terminations
```

---

## The 5 Phase Goals — Coverage After 10 Iterations

| Phase | Goal | Coverage | What's NOT covered |
|---|---|---|---|
| 1 | Tester 7/7 | **6/7** | Verify account — out of scope per codebase evidence (zero email adapters, zero IMAP, zero OTP solvers) |
| 2 | OperationContext 7 fields | **7/7** | All 7 fields on `EngagementState`: `identities`, `sessions`, `resources`, `captured_requests`, `discovered_routes` (existing `recon_context`), `obstacles`, `findings` (existing) |
| 3 | State manipulation 5/5 | **5/5** | CreateOrDiscover (ResourceCreationStrategy) + RequestCapture + Switch + Replay + Analyze — all built |
| 4 | Obstacle reasoning | **6 obstacle types** | email_verification_required, captcha, 2fa, rate_limited, account_locked, email_exists — all detected, recorded, workflow continues |
| 5 | Workflow execution | **BolaWorkflow** | Base `Workflow` class generic enough for IDOR, BFLA, horizontal/vertical privesc variants |

---

## Rollback Runbook

```bash
# Scenario 1: BolaWorkflow crashes in production
redis-cli SET "feature_flag:bola_workflow" 0
# → next scan task runs DualAuthScanner (legacy path)

# Scenario 2: to_dict schema breaks SSE consumer (step 1 regression)
git revert <commit-hash-for-step-1>
# → new fields removed, backward compat restored

# Scenario 3: Need to revert all 5 steps
git revert <step-1-hash>..<step-5-hash>
# → entire V3 workflow reverted, codebase back to pre-V3 state

# Scenario 4: EngagementState corrupted mid-engagement by workflow bug
# Manual: delete the corrupt Redis cache key
redis-cli DEL "engagement_state:{engagement_id}"
# → next task_context load skips Redis, reconstructs from Postgres
```

---

## Mitigation Log

| Iteration | Shortcoming | Mitigation |
|---|---|---|
| 1 | `to_dict()` saves counts only, not data | Add `to_dict_full()` for workflow; use `to_snapshot_dict()` for Redis |
| 1 | `add_observation` truncates aggressively | Workflow records via `record_tool_execution()` (no cap) |
| 2 | `bump_version` saves summary, not full state | Use `DecisionCheckpoint` for per-step persistence (reuses existing `agent_decision_log` table) |
| 3 | `EngagementState` has no mutex | Not needed — workflow runs single-threaded; `DistributedLock` prevents concurrent engagement writes |
| 4 | Detector-to-obstacle conversion needs working code change | **Avoided entirely** — wrapper pattern in `steps.py` parses stdout JSON; `register_tool.py` and `login_tool.py` unchanged |
| 5 | `SoftTimeLimitExceeded` kills engagement | Workflow catches step exceptions, records as obstacles. Only Celery-level timeouts propagate. |
| 6 | E2E test could flake (port collisions, thread timing) | Exclude from CI, run manually: `pytest tests/ -k "not e2e"` |
| 7 | Credential logging risk | Audit rule: never log identity['password'] or session.cookies. `to_dict_full()` explicitly excludes them. |
| 8 | Feature flag key collision | Name key `"feature_flag:bola_workflow"` to match existing convention. |
| 9 | Redis TTL expiry mid-workflow | `_bump_version()` called every ~6s — TTL reset before 300s expiry. No risk. |
| PR-1 | `Session.send` patch only captures Python requests (not SPA traffic) | `CapturedRequest` schema with `source` field. Docstring commits to V2 (Playwright, infra at `browser_scan_worker.py:69`) and V3 (mitmproxy). Future backends drop in without schema changes. |
| PR-2 | `CreateResourceStep` assumes uniform POST patterns for all targets | Renamed to `ResourceCreationStrategy`, injected into BolaWorkflow. V1: common POST patterns + GET-fallback. V2+: Playwright form-fill or LLM reasoning. |
| PR-3 | Obstacles recorded but not solved; data model doesn't support future recovery | Obstacle dict gains `recoverable: bool` + `recovery_paths: list[str]`. V1 paths: `skip`, `backoff_and_retry`, `try_login_anyway`. V2 paths will wire to EmailProvider/CaptchaProvider/OtpProvider. |
| PR-4 | No unified return contract across workflow types | `WorkflowResult` dataclass — all workflows return `success`, `findings_created`, `obstacles_encountered`, `identities_created`, `resources_created`, `requests_captured`, `metadata`. Orchestrator dispatches on this without inspecting internals. |
| PR-5 | V1 ReplayStep doesn't refresh CSRF/anti-replay tokens — false negatives possible | Anti-replay risk accepted for V1. Replay rejections become `Obstacle("replay_rejected", recoverable=False)`. V2+ adds per-request token refresh. |
