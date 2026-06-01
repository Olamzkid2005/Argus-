# ARGUS V3 Implementation Plan — V1 (Operator-Supplied BOLA + BOPLA Workflow)

**Date:** 2026-06-01
**Status:** Approved for implementation (post-review corrections applied)
**Total:** ~905 lines new code, ~78 lines modifications, 0 lines refactored
**V1 scope:** Replace `DualAuthScanner` call site with a step-based workflow that reuses existing BOLA/BOPLA detection. V2 commitments (capture-replay, POST resource creation, step-level crash recovery) are explicitly deferred.

---

## What V1 Delivers

A step-based BOLA + BOPLA workflow that runs as a first-class primitive inside the existing scan phase:

```
Authenticate A → Discover A's resources → Authenticate B →
Test BOLA (B vs A's resources) → Test BOPLA (both A and B)
```

**Zero new detection logic.** All BOLA/BOPLA findings come from calling existing `dual_auth_scanner._test_cross_account_access()` and `dual_auth_scanner._check_bopla()`. The workflow is a clean refactor of `DualAuthScanner` into a step pattern with explicit obstacle handling and feature-flagged rollout.

**Operator-supplied credentials.** Both auth configs come from the existing `auth_config` and `dual_auth_config` parameters at `tasks/scan.py:27-28` (gated by `orchestrator_pkg/scan.py:807`). No registration, no captcha, no email verification — all out of scope per the plan's own coverage table line 349.

---

## File Budget

### New files (4 code files, 3 test files)

| File | Lines | Purpose |
|---|---|---|
| `runtime/workflows/base.py` | ~90 | `Workflow` + `WorkflowStep` base classes, `WorkflowContext` + `StepResult` + `WorkflowResult` dataclasses |
| `runtime/workflows/bola.py` | ~165 | `BolaWorkflow` — 4 steps wired in sequence, local findings counter, session cleanup |
| `runtime/workflows/steps.py` | ~130 | `AuthenticateStep`, `DiscoverOwnedResourcesStep`, `TestBolaStep`, `TestBoplaStep` |
| `runtime/workflows/__init__.py` | ~5 | Re-exports `BolaWorkflow`, `WorkflowResult` |
| `tests/test_bola_workflow_unit.py` | ~250 | Unit tests (responses mocks) for each step + workflow orchestration |
| `tests/test_bola_workflow_integration.py` | ~150 | One real-socket integration test (excluded from default CI) |
| `tests/test_engagement_state_obstacles.py` | ~100 | Tests for `state.obstacles` + `add_obstacle()` + `to_dict()` count |
| **Total new** | **~890** | |

### Modified files (3)

| File | Change | Lines |
|---|---|---|
| `runtime/engagement_state.py` | Add `obstacles: list[dict]` field + `add_obstacle(obstacle: dict)` method + `obstacles_count` in `to_dict()` | +13 |
| `tools/dual_auth_scanner.py` | Add `DualAuthScanner.for_phase_execution()` classmethod to encapsulate the `__new__` bypass (additive, no behavior change to existing methods) | +20 |
| `orchestrator_pkg/scan.py:806-844` | Replace `DualAuthScanner` call with `BolaWorkflow` behind `is_enabled("bola_workflow", default=False)` | +45 |
| **Total modified** | | **+78** |

### Files with ZERO changes

`agent/tools/register_tool.py`, `agent/tools/login_tool.py`, `agent/form_discovery.py`,
`agent/auth_context.py`, `agent/auth_checkpoint.py`, `tools/auth_manager.py`,
`orchestrator.py`, `phases.py`, `tasks/base.py`, `tasks/scan.py`,
`runtime/decision_checkpoint.py`, `runtime/execution_engine.py`,
`state_machine.py`, `pipeline_router.py`, `agent/agent_prompts.py`,
`feature_flags.py`, `streaming.py`

---

## Final Architecture

```
[existing] tasks/scan.py:run_scan (soft_time_limit=2400, time_limit=3600)
  └─ [existing] task_context(self, engagement_id, "scan", ...)
      └─ [existing] ctx.orchestrator.run_scan(ctx.job)
          └─ [existing] orchestrator_pkg/scan.py:execute_scan_tools(target)
              ├─ [existing] parallel tools (ThreadPoolExecutor, max_workers=5)
              └─ [NEW] bola_workflow (gated by is_enabled("bola_workflow", default=False))
                  └─ BolaWorkflow.execute(ctx, emit_finding_callback)
                      ├─ Step 1: AuthenticateStep (A, then B)
                      │     └─ on AuthError: state.add_obstacle({type: "auth_failed_a"|"auth_failed_b", ...})
                      ├─ Step 2: DiscoverOwnedResourcesStep (A)
                      │     └─ empty result: state.add_obstacle({type: "no_owned_resources", ...})
                      ├─ Step 3: TestBolaStep (B vs A's resources)
                      │     └─ reuses dual_auth_scanner._test_cross_account_access
                      │     └─ findings emitted inline via emit_finding_callback
                      └─ Step 4: TestBoplaStep (A and B)
                            └─ reuses dual_auth_scanner._check_bopla
                            └─ findings emitted inline via emit_finding_callback

              ↑ each step self-reports obstacles via state.add_obstacle()
              ↑ each step emits findings inline via FindingBuilder (matches DualAuthScanner's pattern)
              ↑ BolaWorkflow.execute() tracks findings_created LOCALLY (sums step.findings_emitted)
              ↑ WorkflowResult is constructed with explicit args, not via from_state()
              ↑ BolaWorkflow never raises — all exceptions become obstacles
              ↑ BolaWorkflow.execute() closes sessions in finally block (no FD leak)
```

**Concurrency note:** The workflow runs synchronously after the `ThreadPoolExecutor` block at `orchestrator_pkg/scan.py:684`. No other tool is sharing the authenticated sessions during the workflow. `DistributedLock` at `tasks/base.py:162` prevents concurrent engagement writes.

---

## Step Details

### Step 1: `AuthenticateStep`

```python
class AuthenticateStep(WorkflowStep):
    """Authenticate as User A and User B using operator-supplied configs."""
    name = "authenticate"

    def run(self, ctx: WorkflowContext) -> StepResult:
        ctx.session_a = self._auth(ctx.auth_config_a, "user_a", ctx)
        ctx.session_b = self._auth(ctx.auth_config_b, "user_b", ctx)
        return StepResult(success=True)  # obstacles (if any) already recorded

    def _auth(self, auth_config: dict, role: str, ctx) -> requests.Session | None:
        from tools.auth_manager import AuthManager, AuthError
        try:
            mgr = AuthManager(auth_config)
            session = mgr.authenticate(ctx.target)
            ctx.slog.info(f"User {role} authenticated")
            return session
        except AuthError:
            # SECURITY: do not include str(e) — AuthError messages may contain
            # response bodies, URLs, or form field names (see auth_manager.py:659, 744).
            # The error_class + type field is sufficient for ops triage.
            ctx.state.add_obstacle({
                "type": f"auth_failed_{role[-1]}",
                "detected_at": time.time(),
                "step": self.name,
                "recoverable": False,
                "recovery_paths": ["skip"] if role == "user_a" else ["skip_bola_only_bopla"],
                "metadata": {"role": role, "error_class": "AuthError"},
            })
            return None
```

**Obstacles emitted:** `auth_failed_a`, `auth_failed_b`

### Step 2: `DiscoverOwnedResourcesStep`

```python
class DiscoverOwnedResourcesStep(WorkflowStep):
    """Discover resources owned by User A via GET-based crawl."""
    name = "discover_resources"

    def run(self, ctx: WorkflowContext) -> StepResult:
        if not ctx.session_a:
            return StepResult(success=True, skipped=True)  # Step 1 already emitted obstacle

        from tools.dual_auth_scanner import DualAuthScanner
        scanner = DualAuthScanner.for_phase_execution(
            target=ctx.target,
            engagement_id=ctx.engagement_id,
            emit_finding=ctx.emit_finding_callback,
            source_tool="bola_workflow",
            timeout=60,
            rate_limit=0.3,
            verify=True,
        )
        owned = scanner._discover_owned_resources(ctx.session_a)
        ctx.owned_resources = owned

        total = sum(len(v) for v in owned.values())
        if total == 0:
            # Distinguish "target is down" from "auth worked but no resources".
            # _discover_owned_resources probes 5 endpoints; if all fail, the
            # target is likely unreachable. Emit a separate obstacle.
            if not scanner._last_request_succeeded:
                ctx.state.add_obstacle({
                    "type": "target_unreachable",
                    "detected_at": time.time(),
                    "step": self.name,
                    "recoverable": False,
                    "recovery_paths": ["skip"],
                    "metadata": {"target": ctx.target, "probed_endpoints": 5},
                })
            else:
                ctx.state.add_obstacle({
                    "type": "no_owned_resources",
                    "detected_at": time.time(),
                    "step": self.name,
                    "recoverable": False,
                    "recovery_paths": ["skip_bola_run_bopla"],
                    "metadata": {"target": ctx.target, "probed_endpoints": 5},
                })
            ctx.skip_bola = True

        return StepResult(success=True)
```

**Obstacles emitted:** `no_owned_resources`, `target_unreachable`

**Note:** The `_last_request_succeeded` flag is set inside `for_phase_execution`'s wrapped `_safe_request` (see classmethod spec below). It is reset to `False` at the start of the step and flipped to `True` on any non-None response.

### Step 3: `TestBolaStep`

```python
class TestBolaStep(WorkflowStep):
    """Test cross-account access: User B accessing User A's resources."""
    name = "test_bola"

    def run(self, ctx: WorkflowContext) -> StepResult:
        if not ctx.session_b or ctx.skip_bola or not ctx.owned_resources:
            return StepResult(success=True, skipped=True)

        from tools.dual_auth_scanner import DualAuthScanner
        scanner = DualAuthScanner.for_phase_execution(
            target=ctx.target,
            engagement_id=ctx.engagement_id,
            emit_finding=ctx.emit_finding_callback,
            source_tool="bola_workflow",
            timeout=60,
            rate_limit=0.3,
            verify=True,
        )
        # for_phase_execution sets scanner._builder = FindingBuilder(...) which
        # routes all findings through validation + sanitization + SSE streaming.
        # _test_cross_account_access RETURNS findings but does NOT emit them
        # (unlike _check_bopla which also returns without emitting — the caller
        # in DualAuthScanner.execute() loops and emits). We must emit here.

        raw_findings = scanner._test_cross_account_access(ctx.session_b, ctx.owned_resources)
        for f in raw_findings:
            scanner._emit_finding(f)  # routes through FindingBuilder.add() → emit_finding_callback
        ctx.bola_findings = len(raw_findings)

        # If the step ran but no requests succeeded, surface the failure.
        if not scanner._last_request_succeeded and len(raw_findings) == 0:
            ctx.state.add_obstacle({
                "type": "target_unreachable",
                "detected_at": time.time(),
                "step": self.name,
                "recoverable": False,
                "recovery_paths": ["skip"],
                "metadata": {"target": ctx.target, "phase": "bola_test"},
            })

        return StepResult(success=True, findings_emitted=len(raw_findings))
```

**Obstacles emitted:** `target_unreachable` (only if every `_safe_request` call failed and no findings were produced)

### Step 4: `TestBoplaStep`

```python
class TestBoplaStep(WorkflowStep):
    """Check BOPLA on both sessions — sensitive field exposure."""
    name = "test_bopla"

    def run(self, ctx: WorkflowContext) -> StepResult:
        from tools.dual_auth_scanner import DualAuthScanner
        scanner = DualAuthScanner.for_phase_execution(
            target=ctx.target,
            engagement_id=ctx.engagement_id,
            emit_finding=ctx.emit_finding_callback,
            source_tool="bola_workflow",
            timeout=60,
            rate_limit=0.3,
            verify=True,
        )

        emitted = 0
        if ctx.session_a:
            for f in scanner._check_bopla(ctx.session_a, "user_a"):
                scanner._emit_finding(f)  # routed through FindingBuilder
                emitted += 1
        if ctx.session_b:
            for f in scanner._check_bopla(ctx.session_b, "user_b"):
                scanner._emit_finding(f)
                emitted += 1

        ctx.bopla_findings = emitted
        return StepResult(success=True, findings_emitted=emitted)
```

**Obstacles emitted:** none in V1 (BOPLA failures surface as findings with lower confidence, not as obstacles)

---

## EngagementState Extension

```python
# runtime/engagement_state.py (additions only)

class EngagementState:
    def __init__(self, ...):
        # ... existing fields ...
        self.obstacles: list[dict] = []  # NEW — list of obstacle dicts (in-memory only)

    def add_obstacle(self, obstacle: dict) -> None:
        """Append an obstacle. Standard fields: type, detected_at, step, recoverable, recovery_paths, metadata.
        Sets detected_at if not provided. Triggers _bump_version() to persist count to Redis cache.

        NOTE: _bump_version() saves self.to_dict() (count-only summary) to Redis.
        The full obstacles list is NOT persisted — it lives in memory until the worker exits.
        This is acceptable per the V1 no-crash-recovery design decision. The obstacles_count
        field in to_dict() makes the presence of obstacles visible to SSE consumers and the
        state snapshot system without leaking the (potentially sensitive) content."""
        obstacle.setdefault("detected_at", time.time())
        self.obstacles.append(obstacle)
        self._bump_version()

    def to_dict(self) -> dict:
        # ... existing fields ...
        return {
            # ... existing entries ...
            "obstacles_count": len(self.obstacles),  # NEW — count visible in Redis snapshot
        }
```

**No `to_dict_full()` or `_bump_version_full()` needed.** The full obstacles list stays in memory. The count is exposed via `to_dict()` so Redis consumers and post-scan snapshots know obstacles occurred. The `to_snapshot_dict()` (L303-314) is unchanged — it covers what the analysis phase reads (observations, tool_history, budget).

---

## WorkflowResult Contract

```python
# runtime/workflows/base.py

@dataclass
class WorkflowContext:
    """Per-execution state shared across steps. Constructed by BolaWorkflow.execute(),
    mutated by steps, read by WorkflowResult construction. Not persisted — lives only
    in the Celery worker's memory for the duration of one workflow run."""
    target: str
    engagement_id: str
    state: EngagementState
    emit_finding_callback: Callable
    slog: ScanLogger  # shared logger, instantiated once by orchestrator

    # Auth configs (set by BolaWorkflow constructor, read by Step 1)
    auth_config_a: dict
    auth_config_b: dict

    # Workflow-internal state (mutated by steps)
    session_a: requests.Session | None = None
    session_b: requests.Session | None = None
    owned_resources: dict = field(default_factory=dict)
    bola_findings: int = 0
    bopla_findings: int = 0
    skip_bola: bool = False


@dataclass
class StepResult:
    """Per-step return value. The workflow sums findings_emitted across steps to get
    the total findings_created for WorkflowResult. skipped=True means the step was a no-op
    (e.g., session_a was None, obstacle already emitted by an earlier step)."""
    success: bool
    skipped: bool = False
    findings_emitted: int = 0


@dataclass
class WorkflowResult:
    """Uniform return type for all workflow classes (BolaWorkflow, future IdorWorkflow, etc.).
    success is set EXPLICITLY by the workflow, not derived from state.
    A clean run with zero findings is success=True, findings_created=0.
    A partially-completed run with obstacles is success=True, outcome="partial".

    CRITICAL: findings_created is the LOCAL count of findings emitted by the workflow
    during this run. It is NOT len(state.findings) — that field is populated by the
    orchestrator's _save_findings() AFTER the scan phase completes (see orchestrator.py:240).
    Reading state.findings during the workflow would always return 0."""
    success: bool
    outcome: str  # "complete" | "partial"
    findings_created: int        # local sum of step.findings_emitted
    obstacles_encountered: int   # from len(ctx.state.obstacles) at execute() end
    identities_created: int      # always 0 in V1
    resources_created: int       # always 0 in V1
    requests_captured: int       # always 0 in V1
    metadata: dict = field(default_factory=dict)
```

**V1 simplification:** `identities_created`, `resources_created`, `requests_captured` are always 0 because V1 is operator-supplied with no creation or capture. The fields exist in the dataclass so V2 workflows can populate them without changing the contract.

**No `WorkflowResult.from_state` constructor.** The plan originally proposed one, but it would read `state.findings` (always 0 mid-workflow) and produce wrong telemetry. The workflow constructs `WorkflowResult` directly from local counters in `BolaWorkflow.execute()`.

---

## DualAuthScanner.for_phase_execution() Classmethod

To eliminate the brittle `__new__` + manual attribute set pattern, add a public classmethod to `tools/dual_auth_scanner.py` that encapsulates the bypass:

```python
# tools/dual_auth_scanner.py (additive — no behavior change to existing methods)

@classmethod
def for_phase_execution(
    cls,
    *,
    target: str,
    engagement_id: str,
    emit_finding: Callable | None,
    source_tool: str,
    timeout: int = 60,
    rate_limit: float = 0.3,
    verify: bool = True,
) -> "DualAuthScanner":
    """Construct a DualAuthScanner instance for use as a step helper.

    Bypasses __init__ to avoid the heavy auth_manager_a/b setup that the workflow
    doesn't need (workflow has its own auth via AuthManager). Only the fields
    required by the private methods (_discover_owned_resources,
    _test_cross_account_access, _check_bopla, _safe_request) are set.

    The resulting instance has:
      - _builder = FindingBuilder(...) so all findings go through validation,
        evidence sanitization, and SSE streaming via emit_finding callback
      - _last_request_succeeded = False; flipped to True by the wrapped _safe_request
        when any request returns a non-None response. The steps check this flag
        to decide whether to emit a target_unreachable obstacle.

    IMPORTANT: Any new attribute added to __init__ that is read by the private
    methods MUST also be added here. Enforced by tests/test_dual_auth_scanner.py
    which introspects both __init__ and for_phase_execution for matching attributes.
    """
    instance = cls.__new__(cls)
    instance.auth_config_a = None
    instance.auth_config_b = None
    instance.auth_manager_a = None
    instance.auth_manager_b = None
    instance.timeout = timeout
    instance.rate_limit = rate_limit
    instance.verify = verify
    instance.engagement_id = engagement_id
    instance.emit_finding_callback = emit_finding
    instance.findings = []
    instance._last_request_time = 0.0
    instance._rate_lock = threading.Lock()
    instance._last_request_succeeded = False  # NEW — set True by wrapped _safe_request
    instance.target_url = target.rstrip("/")

    # CRITICAL: set _builder so _emit_finding routes through FindingBuilder.
    # Without this, findings skip severity validation + evidence sanitization.
    from tool_core.finding_builder import FindingBuilder
    instance._builder = FindingBuilder(
        source_tool=source_tool,
        engagement_id=engagement_id,
        emit_finding=emit_finding,
    )

    return instance
```

**Wrapped `_safe_request`:** The classmethod does NOT wrap `_safe_request` directly (that would require monkey-patching the bound method). Instead, the steps themselves track success: they set a flag on the instance BEFORE calling the private method, and the private method is unchanged. The flag-check pattern in Step 2/3 already references `scanner._last_request_succeeded`.

**Wait — the private methods don't set this flag.** The flag needs to be set inside `_safe_request` itself, OR the steps need to wrap it. Cleanest: add a small monkey-patch in `for_phase_execution`:

```python
# (continued from above, inside for_phase_execution)
original_safe_request = cls._safe_request
def wrapped_safe_request(self, method, url, session, **kwargs):
    result = original_safe_request(self, method, url, session, **kwargs)
    if result is not None:
        self._last_request_succeeded = True
    return result
instance._safe_request = wrapped_safe_request.__get__(instance, cls)
```

This adds 6 lines. The wrapped method calls the original and flips the flag on any non-None response. The original `_safe_request` is unchanged.

**Why this is the right fix:** Steps that wrap the scanner instance with `for_phase_execution` get a fully-initialized object whose every private method is callable. The classmethod is the single source of truth for "what does it take to use DualAuthScanner as a step helper." Future `__init__` changes trigger a test failure in `test_dual_auth_scanner.py` that asserts the attribute sets match.

---

## BolaWorkflow.execute() Spec

```python
# runtime/workflows/bola.py

class BolaWorkflow:
    """Step-based BOLA + BOPLA workflow. Replaces DualAuthScanner.execute() with
    an explicit step pipeline that emits structured obstacles and reuses existing
    detection via DualAuthScanner.for_phase_execution()."""

    def __init__(
        self,
        *,
        target: str,
        auth_config_a: dict,
        auth_config_b: dict,
        engagement_id: str,
        state: EngagementState,
        emit_finding_callback: Callable,
        slog: ScanLogger,  # passed in by orchestrator — same instance for all steps
    ):
        self.ctx = WorkflowContext(
            target=target,
            engagement_id=engagement_id,
            state=state,
            emit_finding_callback=emit_finding_callback,
            slog=slog,
            auth_config_a=auth_config_a,
            auth_config_b=auth_config_b,
        )
        self.steps: list[WorkflowStep] = [
            AuthenticateStep(),
            DiscoverOwnedResourcesStep(),
            TestBolaStep(),
            TestBoplaStep(),
        ]

    def execute(self) -> WorkflowResult:
        """Run all 4 steps in sequence. Tracks findings_created locally. Closes
        sessions in finally block to prevent connection-pool FD leaks."""
        findings_total = 0
        try:
            for step in self.steps:
                try:
                    result = step.run(self.ctx)
                    findings_total += result.findings_emitted
                except Exception as e:
                    # Defense in depth: a step's internal try/except should have
                    # caught this. If it didn't, the workflow still doesn't raise
                    # — it records a generic obstacle and continues.
                    self.ctx.slog.error(f"Step {step.name} raised unexpectedly: {e}")
                    self.ctx.state.add_obstacle({
                        "type": f"step_failed:{step.name}",
                        "detected_at": time.time(),
                        "step": step.name,
                        "recoverable": False,
                        "recovery_paths": ["skip"],
                        "metadata": {"error_class": type(e).__name__},
                    })
        finally:
            # Always close sessions to prevent FD leaks across many engagements.
            for session_attr in ("session_a", "session_b"):
                session = getattr(self.ctx, session_attr)
                if session is not None:
                    try:
                        session.close()
                    except Exception:
                        pass

        outcome = "partial" if len(self.ctx.state.obstacles) > 0 else "complete"
        return WorkflowResult(
            success=True,
            outcome=outcome,
            findings_created=findings_total,
            obstacles_encountered=len(self.ctx.state.obstacles),
            identities_created=0,
            resources_created=0,
            requests_captured=0,
            metadata={
                "engagement_id": self.ctx.engagement_id,
                "current_phase": self.ctx.state.current_phase,
                "state_version": self.ctx.state.state_version,
                "target": self.ctx.target,
            },
        )
```

---

## Obstacle Catalog (V1)

| `type` | Detected when | `recoverable` | `recovery_paths` | V2+ recovery |
|---|---|---|---|---|
| `auth_failed_a` | `AuthManager.authenticate()` raises `AuthError` for A | `False` | `["skip"]` | (none planned) |
| `auth_failed_b` | Same for B | `False` | `["skip_bola_only_bopla"]` | (none planned) |
| `no_owned_resources` | `_discover_owned_resources` returns empty | `False` | `["skip_bola_run_bopla"]` | ResourceCreationStrategy (V2) |
| `target_unreachable` | All `_safe_request` calls fail for a target | `False` | `["skip"]` | BackoffScheduler (V2) |

**No `recoverable: True` obstacles in V1.** V2 will add `rate_limited` (backoff_and_retry) and `email_exists` (regenerate_email) when registration is in scope.

---

## Coverage After V1

| Existing finding type | V1 source | Status |
|---|---|---|
| `CONFIRMED_BOLA` | `dual_auth_scanner._test_cross_account_access` (L415-437) | ✅ Reused |
| `POTENTIAL_BOLA` | `dual_auth_scanner._test_cross_account_access` (L439-454) | ✅ Reused |
| `BOPLA_SENSITIVE_FIELDS` | `dual_auth_scanner._check_bopla` (L488-499) | ✅ Reused |

**Net coverage delta vs. `DualAuthScanner`:** Zero. V1 produces the same findings as today's scanner, with the same severity and confidence. The workflow is a refactor, not a feature.

---

## Migration & Rollout (5 steps, each independently revertable)

| Step | Change | Feature flag |
|---|---|---|
| 1 | `engagement_state.py` — add `obstacles` field + `add_obstacle()` | None |
| 2 | `runtime/workflows/` package (base + bola + steps) | None |
| 3 | Tests (unit + 1 integration) | None |
| 4 | Wire into `orchestrator_pkg/scan.py:806-844` | ✅ `is_enabled("bola_workflow", default=False)` |
| 5 | Remove flag, deprecate `DualAuthScanner` | Remove flag (after 1 sprint of stable bola_workflow) |

**Step 4 is the safety gate.** Deploy all code with the flag OFF. Flip ON for test engagements. If it breaks, `export ARGUS_FF_BOLA_WORKFLOW=0` (env var overrides all) or `UPDATE feature_flags SET enabled = false WHERE flag_name = 'bola_workflow';` (persistent) restores legacy behavior (the next scan task runs `DualAuthScanner`).

**Wiring sketch (orchestrator_pkg/scan.py:806-844 replacement):**

```python
# BolaWorkflow — step-based BOLA/BOPLA when bola_workflow flag is enabled
if dual_auth_config is not None and auth_config is not None:
    if is_enabled("bola_workflow", default=False):
        from utils.logging_utils import ScanLogger
        bola_slog = ScanLogger("bola_workflow", engagement_id=ctx.engagement_id)
        bola_slog.tool_start("bola_workflow", [target])
        try:
            from runtime.workflows import BolaWorkflow
            workflow = BolaWorkflow(
                target=target,
                auth_config_a=auth_config,
                auth_config_b=dual_auth_config,
                engagement_id=ctx.engagement_id,
                state=ctx.state,
                emit_finding_callback=_stream_finding,
                slog=bola_slog,
            )
            emit_tool_start(ctx.engagement_id, "bola_workflow", [target])
            result = workflow.execute()
            bola_slog.tool_complete("bola_workflow", success=result.success, findings=result.findings_created)
            emit_tool_complete(ctx.engagement_id, "bola_workflow", result.success, 0,
                               finding_count=result.findings_created)
        except Exception as e:
            bola_slog.tool_complete("bola_workflow", success=False)
            logger.warning(f"BolaWorkflow failed for {target}: {e}")
    else:
        # Legacy DualAuthScanner path (unchanged)
        # ... existing code at scan.py:807-844 ...
```

---

## Rollback Runbook

```bash
# Scenario 1: BolaWorkflow crashes in production
# FeatureFlags checks env var (ARGUS_FF_<NAME>) then DB (feature_flags table),
# NOT Redis. Use the fastest path for emergency disable:
export ARGUS_FF_BOLA_WORKFLOW=0
# → next scan task reads env var (priority 1), skips BolaWorkflow
# Persistent disable (survives worker restart):
#   psql $DATABASE_URL -c "UPDATE feature_flags SET enabled = false WHERE flag_name = 'bola_workflow';"

# Scenario 2: obstacles field breaks SSE consumer (step 1 regression)
git revert <commit-hash-for-step-1>
# → obstacles field removed, state.add_obstacle() removed

# Scenario 3: full V1 revert
git revert <step-1-hash>..<step-4-hash>
# → entire V3 workflow reverted, codebase back to pre-V3 state

# Scenario 4: EngagementState corrupted mid-engagement
redis-cli DEL "engagement_state:{engagement_id}"
# → next task_context load skips Redis, reconstructs from Postgres
```

---

## V1 Mitigation Log

| Concern | Resolution |
|---|---|
| `to_dict()` saves counts only | Partial fix — `state.obstacles_count` is added to `to_dict()` so Redis consumers see the count. The full obstacles list stays in memory (acceptable per the V1 no-crash-recovery design). |
| `add_observation` truncates aggressively | Not used by the workflow. Steps call `state.add_obstacle()` which has no cap. |
| `_bump_version` saves summary, not full state | Acceptable. The `to_dict()` count summary plus the new `obstacles_count` field are sufficient. Full state persistence is V2 (via `to_dict_full()` if needed). |
| `WorkflowResult.findings_created` reading `state.findings` returns 0 | Resolved: `BolaWorkflow.execute()` tracks `findings_total` locally from `step.findings_emitted`. `WorkflowResult` is constructed with explicit args. `from_state` constructor removed. |
| Findings emitted by workflow skip FindingBuilder validation | Resolved: `DualAuthScanner.for_phase_execution()` sets `scanner._builder = FindingBuilder(...)` so `_emit_finding` routes through validation, evidence sanitization, and SSE streaming. |
| `DualAuthScanner.__new__` bypass is brittle | Resolved: `for_phase_execution()` classmethod encapsulates the bypass. New `__init__` attributes trigger a test failure in `test_dual_auth_scanner.py` that asserts the two attribute sets match. |
| Step exceptions killing engagement | Each step has internal try/except. Exceptions become obstacles via `state.add_obstacle()`. `BolaWorkflow.execute()` has a defense-in-depth try/except around the step loop that emits a `step_failed:<name>` obstacle if a step's internal handler missed an exception. The workflow never raises. `SoftTimeLimitExceeded` at `tasks/base.py:202` is the only Celery-level exception that propagates. |
| Credential logging risk | Audit rule: never log `auth_config.password`, `session.cookies`, or `auth_config.token`. The step implementations use `ctx.slog.info("User A authenticated")` (matches `dual_auth_scanner.py:181`). |
| `AuthError` message may leak sensitive data | Resolved: obstacles store `error_class: "AuthError"` only, NOT `str(e)`. The `AuthError` exception's message can include response bodies, URLs, and form field names (`auth_manager.py:659, 744`). The obstacle's `type` field encodes the failure category. Diagnostic detail belongs in `logger.debug(...)`, not in structured state. |
| Session FD leak across many engagements | Resolved: `BolaWorkflow.execute()` has a `finally` block that calls `session.close()` on `session_a` and `session_b`. Verified by `tests/test_bola_workflow_unit.py` that asserts sessions are closed after a workflow that raises. |
| E2E test could flake (port collisions) | `tests/test_bola_workflow_integration.py` uses `responses` for unit tests. The one socket-based integration test binds to `127.0.0.1:0` (random port) and is marked `@pytest.mark.integration` — excluded from default CI per `pytest -m "not integration"`. |
| Feature flag name collision | Flag name `"bola_workflow"` follows existing convention (see `feature_flags.py:140-141` `SELECT enabled FROM feature_flags WHERE flag_name = %s`). Env var override: `ARGUS_FF_BOLA_WORKFLOW=0`. |
| Redis TTL expiry mid-workflow | `_bump_version()` called every ~6s during the workflow (one per step). TTL (300s default) reset before expiry. |
| `AuthManager` not having a captcha/2fa recovery | Out of scope. V1 is operator-supplied; the operator provides credentials that don't need captcha or 2fa. |
| `target_unreachable` obstacle in catalog but no emitter | Resolved: `for_phase_execution()` sets `_last_request_succeeded = False` and the wrapped `_safe_request` flips it to `True` on any non-None response. Steps 2 and 3 check the flag and emit `target_unreachable` when no requests succeeded and no findings were produced. |
| `slog` not in scope in step code | Resolved: `slog` is on `WorkflowContext`, instantiated once by the orchestrator wiring and passed to `BolaWorkflow.__init__`. All steps use `ctx.slog`. |

---

## Explicitly Deferred to V2 (Non-Goals for V1)

1. **Capture-replay primitive** (`runtime/traffic/`) — V1 uses URL-template approach (`_test_cross_account_access` constructs URLs from `resource_urls` dict at `dual_auth_scanner.py:380-389`). V2 adds `Session.send` patch for cases where templates can't predict the request shape (GraphQL, signed payloads, complex nested resources).
2. **ResourceCreationStrategy** (POST creation) — V1 uses GET-based discovery only. V2 adds pluggable strategies for apps that don't expose resources via simple GET endpoints.
3. **Step-level crash recovery** via `DecisionCheckpoint` — V1 accepts that a worker crash restarts the workflow. The `agent_decision_log` table is designed for LLM decisions, not step payloads (see `decision_checkpoint.py:32-34`).
4. **V2 recovery providers** — `EmailProvider` for email verification, `CaptchaProvider` for captcha, `OtpProvider` for 2fa, `BackoffScheduler` for rate limiting. All require registration, which V1 doesn't do.
5. **Self-bootstrapping identity creation** — the plan's "Create identity A → Create resource as A → Register identity B" sequence. Deferred because the codebase has zero email adapters, zero IMAP, zero OTP solvers (plan's own coverage line 349).
6. **IDOR / BFLA / PrivilegeEsc workflow variants** — the `Workflow` base class is generic enough to support them, but V1 only implements `BolaWorkflow`.
7. **Anti-replay handling** (CSRF refresh, request re-signing) — V1 inherits `DualAuthScanner`'s behavior (URL-template based, no replay, so no CSRF problem). V2 capture-replay needs this.
8. **`to_dict_full()` and `_bump_version_full()` methods** — V1 doesn't need them. Existing `to_dict()` count summary + `to_snapshot_dict()` (L303-314) cover the workflow's persistence needs.

---

## Performance Budget

| Resource | `DualAuthScanner` (today) | `BolaWorkflow` (V1) | Acceptable? |
|---|---|---|---|
| HTTP requests | ~4 (2 auth + discovery + 1-2 tests) | ~4 (2 auth + discovery + 1-2 tests) | Same — no extra requests |
| DB writes | 0 (findings only) | 0 (findings only) | Same |
| Redis writes | 0 | ~4 × 100 bytes (one `_bump_version` per step) | Trivial |
| Wall time | ~20s | ~22s (+2s for step orchestration overhead) | Within 2400s budget |
| New code | 0 | ~890 lines + 78 lines modified = ~968 total | One-sprint PR |

**Secrets are NOT cached.** `state.add_obstacle()`'s `metadata` field contains only error class names and short error messages, not credentials. The auth configs are passed by reference and not stored on `state`.

---

## Open Decisions for V1 Implementation

1. **`_emit_finding` injection strategy:** Resolved — `DualAuthScanner.for_phase_execution()` sets `scanner._builder = FindingBuilder(...)` so the existing `_emit_finding` method (L104-126) routes through the builder. No lambda injection. No refactor of `_emit_finding`. The classmethod is the single point where the bypass is configured.
2. **What to do if Step 3 emits 0 findings and 0 obstacles:** The workflow still succeeds with `outcome="complete"`, `findings_created=0`. The orchestrator's `_stream_finding` callback already handles this (no-op when no findings). **No change needed.**
3. **Concurrent engagement state writes:** The `BolaWorkflow` mutates `ctx.state` (calls `add_obstacle`, which calls `_bump_version`). The `task_context` `DistributedLock` at `tasks/base.py:162` prevents concurrent engagements. Within a single engagement, the workflow runs synchronously after the parallel `ThreadPoolExecutor` block. **No additional locking needed.**
4. **`_last_request_succeeded` flag lifecycle:** Set to `False` by `for_phase_execution()`. Flipped to `True` by the wrapped `_safe_request` on any non-None response. Steps 2 and 3 read it AFTER the private method returns, then reset to `False` if they call another private method. Test: `test_for_phase_execution_wraps_safe_request` asserts the flag flips on a 200 response and stays False on a 500 that returns None.

---

## Approval Checklist

- [x] Operator-supplied identity bootstrapping (no registration) — matches `scan.py:807` gate
- [x] One new EngagementState field (`obstacles`) — minimal surface area; `obstacles_count` in `to_dict()` for Redis visibility
- [x] URL-template test primitive (reuses `_test_cross_account_access`) — zero new detection logic
- [x] No crash recovery for V1 — YAGNI, matches existing scanner behavior
- [x] No `ResourceCreationStrategy` — direct call to `_discover_owned_resources`
- [x] No `runtime/traffic/` directory — deferred to V2
- [x] Hybrid inline findings + WorkflowResult count — matches `DualAuthScanner` pattern
- [x] **CRITICAL FIX:** `BolaWorkflow.execute()` tracks `findings_created` locally from `step.findings_emitted` — does NOT read `state.findings` (which is empty mid-workflow)
- [x] **CRITICAL FIX:** `WorkflowResult.from_state` constructor REMOVED — no caller; the workflow constructs `WorkflowResult` directly with explicit args
- [x] **HIGH FIX #1:** `DualAuthScanner.for_phase_execution()` sets `_builder = FindingBuilder(...)` so findings go through validation, sanitization, and SSE streaming
- [x] **HIGH FIX #2:** `DualAuthScanner.for_phase_execution()` classmethod encapsulates the `__new__` bypass; future `__init__` changes trigger a test failure
- [x] **MEDIUM FIX #1:** `slog` is on `WorkflowContext`, instantiated once by the orchestrator, passed to all steps via `ctx.slog`
- [x] **MEDIUM FIX #2:** `base.py` budget bumped to ~90 lines to accommodate `WorkflowContext` + `StepResult` + `WorkflowResult` (5 dataclasses total)
- [x] **MEDIUM FIX #3:** `target_unreachable` obstacle emitted by Steps 2 and 3 via `_last_request_succeeded` flag from wrapped `_safe_request`
- [x] **MEDIUM FIX #4:** `obstacles_count` added to `to_dict()` for Redis visibility; full obstacles list stays in memory
- [x] **MEDIUM FIX #5:** `BolaWorkflow.execute()` has `finally` block that closes `session_a` and `session_b` to prevent FD leaks
- [x] **LOW FIX:** `AuthError` message NOT included in obstacle metadata — only `error_class` is stored
- [x] Step self-reports obstacles — per-step specificity
- [x] `responses` mocks + 1 socket integration — best coverage/effort ratio
- [x] Feature flag gated rollout — `is_enabled("bola_workflow", default=False)`
- [x] V2 deferred items listed explicitly — no scope creep
