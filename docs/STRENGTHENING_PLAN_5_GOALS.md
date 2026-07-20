# Argus — Strengthening Plan for the Five Core Goals

> **Date:** July 20, 2026
> **Scope:** Codebase-wide assessment across all five product goals
> **Methodology:** Source-level review of ~40 key files across `argus-workers`, tooling, reporting, and orchestration layers

---

## Table of Contents

1. [Current State Assessment](#1-current-state-assessment)
   - [Goal 1: Autonomous Security Testing](#goal-1-autonomous-security-testing)
   - [Goal 2: Intelligent Workflow Planning](#goal-2-intelligent-workflow-planning)
   - [Goal 3: Security Tool Orchestration](#goal-3-security-tool-orchestration)
   - [Goal 4: Security Reasoning & Findings Correlation](#goal-4-security-reasoning--findings-correlation)
   - [Goal 5: Reporting & Knowledge Capture](#goal-5-reporting--knowledge-capture)
2. [Prioritized Action Plan](#2-prioritized-action-plan)
   - [Tier 1: High Impact, Moderate Effort](#tier-1-high-impact-moderate-effort)
   - [Tier 2: High Impact, Higher Effort](#tier-2-high-impact-higher-effort)
   - [Tier 3: Important But Not Blocking](#tier-3-important-but-not-blocking)
3. [Dependency Map](#3-dependency-map)
4. [Success Metrics](#4-success-metrics)

---

## 1. Current State Assessment

### Goal 1: Autonomous Security Testing — ✅ Mostly Achieved

**What's there:**

- `IntentParser` → LLM translates natural language to structured config with regex-based fallback for offline mode
- `dispatch_task.py` → bridges Node.js TUI → Celery worker pipeline via stdin JSON
- `Orchestrator.run()` → auto-transitions through 6 job types: `recon → scan → analyze → report` (+ `post_exploit`, `verification`)
- `pipeline_router.py` → routes recon/scan with retry + exponential backoff on transient failures
- Full TUI layer (`scan.tsx`, `app.tsx`) for user interaction
- `state_machine.py` → engagement lifecycle management with proper state transitions
- `checkpoint_manager.py` → partial checkpoint infrastructure (exists but not fully wired)

**Gaps:**

| # | Gap | Impact | Evidence |
|---|---|---|---|
| 1.1 | **No offline/minimal mode** — Full autonomy requires Docker (Postgres + Redis + Celery). A user running `argus assess https://x.com` without infrastructure gets nothing. | High — blocks adoption for individual security engineers | `dispatch_task.py` requires `DATABASE_URL`; `Orchestrator.__init__` connects to Postgres + Redis |
| 1.2 | **No session persistence across crashes** — If the worker dies mid-engagement, there's no resume-from-checkpoint flow. `checkpoint_manager.py` and `snapshot_manager.py` exist but aren't wired as a recovery path. | Medium — lost work on worker restart | `checkpoint_manager.py` exists but is not called from `Orchestrator.run()` |
| 1.3 | **No standalone Python CLI** — The CLI lives in the TypeScript TUI layer, which calls `dispatch_task.py` via stdin. There's no `pip install argus-workers && argus assess` experience. | Medium — users need the full TUI stack | CLI is in `opencode/src/argus/tui/`, no `cli.py` entry point |

### Goal 2: Intelligent Workflow Planning — ⚠️ Partially Achieved (Biggest Gap)

**What's there:**

- `AdaptiveWorkflowPlanner` → 11 signal-driven phases, topological sort for dependency resolution, dynamic chaining via `update_plan_from_results()`, tool deduplication
- `IntentParser` → extracts priority classes, aggressiveness, tech hints from natural language
- `WorkflowIntelligenceEngine` → post-execution metrics analysis and optimization recommendations
- `SwarmAgent` → activates specialist agents (IDOR, Auth, API) based on recon signals
- Plan formatted and injected into LLM agent's `initial_context` as `adaptive_plan` text

**Gaps:**

| # | Gap | Impact | Evidence |
|---|---|---|---|
| 2.1 | **Static, not adaptive** — The planner evaluates all phases once at plan time. It doesn't re-evaluate mid-execution. If recon missed a login page but the scan finds one, no new auth-testing phase is created. | High — misses cross-phase discoveries | `build_plan()` called once in `run_scan()`; no re-evaluation hook |
| 2.2 | **No multi-step reasoning** — The planner doesn't do "found login page → infer auth testing → session analysis → role testing → BOLA testing" as a chained reasoning path. Each phase activates independently. | Medium — phases are independent, not inferential | Each `activate_fn` checks isolated ReconContext attributes |
| 2.3 | **No plan-versus-actual tracking** — After execution, there's no comparison of "the plan said to test X, did we actually test X?" | Medium — no coverage metrics | `get_plan_summary()` exists but is observability-only |
| 2.4 | **Plan not driving execution** — The plan is injected as agent context text, but the orchestrator doesn't use it to actively select phases. The deterministic fallback runs all tools regardless of the plan. | Medium — plan is advisory, not directive | `_run_scan_with_fallback()` doesn't reference `_adaptive_plan` |

### Goal 3: Security Tool Orchestration — ✅ Strongly Achieved

**What's there:**

- 50+ tools in `tool_definitions.py` with full declarative metadata (phases, timeouts, signal quality, requires gates, parameters, exploit categories)
- `ToolRegistry` with PATH scanning, TTL-based caching, availability checking
- `ToolRunner` with sandboxing (locked env vars, temp directory), circuit breakers (per-tool, configurable threshold + cooldown), rate limiting (per-host semaphore), scope validation, dangerous-pattern detection (subprocess, filesystem, database destruction)
- `MCPToolBridge` for sandboxed execution routing through `ToolRunner`
- `ScopeValidator` enforced at multiple layers (orchestrator, MCP bridge, tool runner)
- Tool gating via `ToolRequires` (tech_contains, recon_signals, target_scheme)
- `_AGENT_INTERNAL_TOOLS` frozenset for Python-native tools (register, login, etc.)

**Gaps:**

| # | Gap | Impact | Evidence |
|---|---|---|---|
| 3.1 | **No container-level sandboxing** — The `ToolRunner` uses subprocess with locked environment vars and a temp sandbox directory, but there's no seccomp/container isolation. This is the single biggest attack-surface gap. | Critical — generated exploit code runs without isolation | `ToolRunner.run()` uses `subprocess.Popen` with no container boundary |
| 3.2 | **No tool health checks** — `ToolRegistry` passively checks PATH at startup but doesn't actively verify tools work (e.g., `nuclei -version`). | Low — tools may silently fail at runtime | `is_available()` only checks `shutil.which()` |
| 3.3 | **No tool version pinning** — Tools are resolved from PATH at runtime; no version management. | Low — reproducibility across environments | No `tool_version` field on `ToolDefinition` |

### Goal 4: Security Reasoning & Findings Correlation — ✅ Strongly Achieved

**What's there:**

- `attack_graph_db.py` → builds dependency graphs from findings with node/link relationships
- `FindingCorrelationEngine` → semantic deduplication, root cause analysis, attack chain detection
- `AttackPathGenerator` → graph analysis + narrative generation
- `HypothesisEngine` (feature-flagged) → generates hypotheses from top findings for targeted testing
- `LLMSynthesizer` → evidence-weighted synthesis with risk scoring, coverage gap detection
- `post_finding_hooks.py` → automated post-finding actions (notifications, triggers)
- `compliance_posture_scorer.py` → compliance framework mapping (SOC 2, HIPAA, PCI)
- `intelligence_engine.py` → LLM-powered findings analysis and correlation

**Gaps:**

| # | Gap | Impact | Evidence |
|---|---|---|---|
| 4.1 | **Hypothesis engine disabled by default** — `HYPOTHESIS_ENGINE` feature flag defaults to `False`. Users don't get hypothesis-driven testing. | Medium — lost predictive capability | `feature_flags.py` default config |
| 4.2 | **No cross-engagement learning** — Each engagement's findings are isolated. No trending, no "this target has the same vulnerability we found last month." | Medium — no portfolio-level visibility | Findings scoped to `engagement_id`, no cross-engagement aggregation |
| 4.3 | **No automated false-positive reduction** — Findings are scored with confidence, but there's no automated retesting of low-confidence findings to confirm or dismiss them. | Low — analyst must manually verify | No verification scheduler in the pipeline |

### Goal 5: Reporting & Knowledge Capture — ✅ Achieved

**What's there:**

- `LLMReportGenerator` → narrative reports with executive summary, technical details, risk scoring
- `ReportGenerationService` → orchestrates LLM report + SBOM generation
- Multiple output formats (markdown, HTML, JSON via `exporter.py`)
- Compliance reporting (SOC 2, HIPAA, PCI)
- `SnapshotManager` → captures engagement state (findings, budget, hypotheses) for reporting
- Report persistence to database via `ReportRepository`
- `compliance_reporting.py` → dedicated compliance posture reporting

**Gaps:**

| # | Gap | Impact | Evidence |
|---|---|---|---|
| 5.1 | **No PDF output** — `report-generator` tool definition lists `markdown, pdf, html` but actual PDF generation isn't implemented. | Medium — clients expect PDF reports | No `weasyprint`/`wkhtmltopdf` integration in `exporter.py` |
| 5.2 | **No `argus report` CLI flow** — Reports are auto-generated at pipeline end, but no on-demand re-generation from existing findings. | Medium — no post-hoc report access | `run_reporting()` only called during pipeline; no standalone entry point |
| 5.3 | **No cross-engagement reporting** — No portfolio view, no trend analysis across engagements. | Low-Medium — no organizational risk view | Reports are per-engagement only |
| 5.4 | **No remediation tracking** — Once findings are reported and fixed, there's no re-scan to verify remediation. | Medium — can't close the loop | No `argus verify <engagement_id>` flow |

---

## 2. Prioritized Action Plan

### Tier 1: High Impact, Moderate Effort

These items close the remaining gaps that have the highest user-facing impact with the least implementation complexity.

---

#### 1.1 Make the Planner Truly Adaptive

**Problem:** The plan is evaluated once and never revisited mid-execution. If the scan phase discovers something recon missed (e.g., a login page behind JS rendering), no new auth-testing phase is triggered.

**Implementation:**

1. **Add `update_from_scan_results(findings)` to `WorkflowPlan`** — Re-evaluates the phase definitions with updated context (merged recon context + scan findings). If findings reveal a login page that recon missed, activate `auth_testing` mid-stream.

2. **Add coverage tracking** — After scan completes, emit `plan.get_coverage_report()` showing which phases ran, which were skipped, and why. Include this in the analysis phase as a `coverage_gaps` field.

3. **Wire plan into deterministic fallback** — The fallback currently runs all tools regardless of the plan. Change it to respect the plan's active phases and skip tools for non-activated phases.

**Files to modify:**
- `orchestrator_pkg/planning/adaptive_planner.py` — add `update_from_scan_results()`
- `orchestrator_pkg/orchestrator.py` — call it after each phase completes
- `orchestrator_pkg/scan.py` — pass plan to `execute_scan_tools()` for phase-aware tool selection

**Estimated effort:** 2-3 days

---

#### 1.2 Add Lightweight Standalone Mode

**Problem:** No autonomy without Docker infrastructure. A security engineer on a laptop can't run `argus assess https://example.com` without starting Postgres, Redis, and a Celery worker.

**Implementation:**

1. **Create `cli.py`** — A standalone Python CLI with `argus assess`, `argus scan`, `argus report` commands using `argparse` or `click`. This bypasses the TUI layer entirely for headless/CI use.

2. **Add `SQLiteBackend`** — Implements the same repository interfaces (`FindingRepository`, `EngagementRepository`, etc.) but stores to a local SQLite file instead of Postgres. This enables `argus assess https://example.com --local` without Docker.

3. **Inline Celery** — For standalone mode, run tasks synchronously in-process instead of dispatching to Celery workers. This eliminates the Redis dependency.

**Files to create:**
- `argus-workers/cli.py` — CLI entry point
- `database/sqlite_backend.py` — SQLite repository implementations

**Files to modify:**
- `orchestrator_pkg/orchestrator.py` — accept optional sync mode

**Estimated effort:** 4-5 days

---

#### 1.3 Enable Hypothesis Engine by Default

**Problem:** `HYPOTHESIS_ENGINE` is feature-flagged off by default. Users don't get predictive, hypothesis-driven testing.

**Implementation:**

1. **Flip default to `True`** in `feature_flags.py`

2. **Wire hypotheses into the planner** — After `HypothesisEngine.generate()` produces hypotheses, pass them to `AdaptiveWorkflowPlanner.build_plan()` so the planner can activate phases based on predicted vulnerabilities (e.g., "potential SQLi → activate input_validation with SQLi focus").

**Files to modify:**
- `argus-workers/feature_flags.py` — change default
- `orchestrator_pkg/orchestrator.py` — pass hypotheses to planner
- `orchestrator_pkg/planning/adaptive_planner.py` — accept hypotheses in `build_plan()`

**Estimated effort:** 1-2 days

---

#### 1.4 Add `argus report` CLI Command

**Problem:** Reports are auto-generated at pipeline end but can't be re-generated on demand from existing findings.

**Implementation:**

1. **Add `argus report <engagement_id> [--format json|markdown|html|pdf]`** to `cli.py` (depends on 1.2)

2. **Implement PDF generation** — Add `weasyprint` dependency and wire HTML → PDF conversion in `reporting/exporter.py`

3. **Add `argus findings <engagement_id> [--severity critical|high]`** — Quick finding lookup without the full report. Useful for CI pipelines and quick triage.

**Files to create:**
- CLI report command module

**Files to modify:**
- `cli.py` — new commands
- `argus-workers/reporting/exporter.py` — PDF support

**Estimated effort:** 2-3 days

---

### Tier 2: High Impact, Higher Effort

---

#### 2.1 Container Sandbox for Chain-Exploit Verification

**Problem:** The single biggest remaining attack surface — no container/seccomp isolation for generated exploit code. The `ToolRunner` uses subprocess with locked env vars, but a malicious or buggy generated exploit can still touch the host filesystem and network.

**Implementation:**

1. **Follow the existing design doc** — Container-based sandboxing (likely Docker or `nsjail`) for running generated PoCs and chain exploits

2. **Add `tool_core/sandbox/container.py`** — Docker SDK or subprocess wrapper that:
   - Pulls a minimal sandbox image (e.g., `alpine:latest`)
   - Mounts only the required inputs (target URL, exploit script)
   - Enforces CPU/memory/timeout limits at the container level
   - Captures stdout/stderr and exit code
   - Destroys container after execution

3. **Add `tool_core/sandbox/seccomp.py`** — Optional seccomp profile for native sandboxing without Docker (uses `python-seccomp`)

**Files to create:**
- `tool_core/sandbox/__init__.py`
- `tool_core/sandbox/container.py`
- `tool_core/sandbox/seccomp.py`

**Files to modify:**
- `tool_core/sandbox.py` — integrate container sandbox as optional execution backend
- `tools/tool_runner.py` — route exploit/verification tools through sandbox

**Estimated effort:** 5-7 days
**Depends on:** Existing design doc in repo

---

#### 2.2 Multi-Step Reasoning Planner

**Problem:** Phases activate independently, not as a chained reasoning path. The planner doesn't do "found login page → infer auth testing → session analysis → role testing" as a multi-step inference.

**Implementation:**

1. **Add `LLMPlannerRefinement`** — Takes the signal-driven plan from `AdaptiveWorkflowPlanner` and asks the LLM: "Given these activated phases, what's the optimal execution order with conditional branching?"

2. **LLM adds phase-specific tool recommendations** — e.g., "for auth_testing, prioritize JWT scanning over basic auth because the tech_stack says Node.js with Passport.js"

3. **Store refined plan as a dependency graph** — Not just a flat ordered list. Include conditional branches: "if auth_testing finds JWT tokens, then run session_analysis with jwt_tool specifically"

**Files to create:**
- `orchestrator_pkg/planning/llm_refiner.py`

**Files to modify:**
- `orchestrator_pkg/planning/adaptive_planner.py` — accept refined plan
- `orchestrator_pkg/orchestrator.py` — call refiner after initial plan

**Estimated effort:** 4-5 days
**Depends on:** 1.1 (adaptive planner foundation)

---

#### 2.3 Cross-Engagement Analytics

**Problem:** No learning across engagements. Each engagement's findings are isolated. No trending, no "this target has the same vulnerability we found last month at a sister company."

**Implementation:**

1. **Add `TrendRepository`** — Aggregates findings across engagements by:
   - Target domain / organization
   - Vulnerability type (CWE, OWASP category)
   - Tech stack (findings per technology)
   - Time (weekly/monthly trends)

2. **Add `argus trends --domain example.com`** — Shows vulnerability recurrence rate, mean time to remediation, most common vulnerability types

3. **Add portfolio risk scoring** — Aggregate risk scores across all engagements for an organization using a simple weighted average of finding severity + confidence

**Files to create:**
- `database/repositories/trend_repository.py`
- CLI analytics commands

**Estimated effort:** 3-4 days

---

### Tier 3: Important But Not Blocking

---

#### 3.1 Tool Health Checks and Version Pinning

**Problem:** No active verification that tools work. `ToolRegistry` checks `shutil.which()` but doesn't verify the binary is functional.

**Implementation:**

1. **Add `tool healthcheck`** — Runs `tool --version` for each registered tool and reports failures in a structured format

2. **Add optional `tool_version` field to `ToolDefinition`** — With semver range support (e.g., `>=3.2.0,<4.0.0`)

3. **Version mismatch → log warning, don't block** — Non-fatal: the user sees "nuclei 2.x may not support -tags flag used by tech_deep_scan phase"

**Files to modify:**
- `tool_core/registry.py` — add version checks
- `tool_definitions.py` — add `tool_version` field

**Estimated effort:** 2 days

---

#### 3.2 Automated False-Positive Reduction

**Problem:** Low-confidence findings aren't auto-retested. The analyst must manually verify every "candidate" level finding.

**Implementation:**

1. **Add `VerificationScheduler`** — Picks findings below a confidence threshold (e.g., `< 0.7`) and re-runs the tool that produced them with more targeted parameters

2. **Confidence decay** — If the tool doesn't reproduce the finding after N attempts, downgrade confidence further

3. **"Not reproduced" status** — Don't dismiss findings, just mark them as "not reproduced" so the analyst can still review them

**Files to create:**
- `tools/verification/scheduler.py`

**Files to modify:**
- `orchestrator_pkg/orchestrator.py` — call scheduler after scan phase

**Estimated effort:** 2-3 days
**Depends on:** 2.1 (safe re-execution via sandbox)

---

#### 3.3 Remediation Verification

**Problem:** Once findings are reported and the team claims they've fixed them, there's no way to re-scan and verify.

**Implementation:**

1. **Add `argus verify <engagement_id>`** — Re-scans only the endpoints where findings were reported. Uses the same tool configuration as the original scan but targets only affected endpoints.

2. **Before/after comparison** — Compare new findings against old. If a previous finding's CVE/type doesn't appear, mark it as "remediated."

3. **Include in report** — Remediation verification section in the next report generation.

**Files to create:**
- CLI verify command

**Files to modify:**
- `orchestrator_pkg/orchestrator.py` — add `run_verification_scan()`
- `reporting/exporter.py` — remediation section

**Estimated effort:** 2-3 days
**Depends on:** 3.2 (verification infrastructure)

---

#### 3.4 Session Resume from Checkpoint

**Problem:** Worker crash loses progress. Mid-engagement restart starts from the beginning.

**Implementation:**

1. **Wire `checkpoint_manager.py` into orchestrator main loop** — After each phase completes, save a checkpoint with: completed phases, findings so far, current state, remaining budget

2. **On restart** — Check for an incomplete engagement with a checkpoint. Resume from the last completed phase, not from the beginning.

3. **Checkpoint cleanup** — Delete checkpoint on successful engagement completion.

**Files to modify:**
- `orchestrator_pkg/orchestrator.py` — call checkpoint save/load
- `checkpoint_manager.py` — verify API matches orchestrator needs

**Estimated effort:** 2 days
**Depends on:** 1.2 (SQLite for checkpoint storage without Postgres)

---

## 3. Dependency Map

```
Tier 1 (Sprint 1 — ~8-13 days)
├── 1.1 Adaptive planner updates       (no deps, 2-3d)
├── 1.2 Standalone CLI + SQLite        (no deps, 4-5d)
├── 1.3 Enable hypotheses              (depends: 1.1, 1-2d)
└── 1.4 Report CLI                     (depends: 1.2, 2-3d)
│
Tier 2 (Sprint 2-3 — ~12-16 days)
├── 2.1 Container sandbox              (no deps, 5-7d)
├── 2.2 LLM refiner                    (depends: 1.1, 4-5d)
└── 2.3 Cross-engagement analytics     (no deps, 3-4d)
│
Tier 3 (Backlog — ~8-10 days)
├── 3.1 Tool health checks             (depends: 2.1, 2d)
├── 3.2 False-positive reduction       (depends: 2.1, 2-3d)
├── 3.3 Remediation verification       (depends: 3.2, 2-3d)
└── 3.4 Session resume                 (depends: 1.2, 2d)
```

**Parallelization strategy:**

| Sprint | Parallel tracks |
|---|---|
| Sprint 1 | **Track A:** 1.1 → 1.3 (adaptive planner), **Track B:** 1.2 → 1.4 (standalone mode + report CLI) |
| Sprint 2 | **Track A:** 2.1 (sandbox, independent), **Track B:** 2.2 (LLM refiner, depends on 1.1) |
| Sprint 3 | **Track A:** 2.3 (analytics), **Track B:** 3.1 (health checks, no blockers) |
| Backlog | 3.2 → 3.3 → 3.4 (sequential chain) |

---

## 4. Success Metrics

| Goal | Metric | Current State | Target (Sprint 3) |
|---|---|---|---|
| **1. Autonomy** | Engagements run without Docker | 0% | 80%+ of basic scans work with `--local` |
| **1. Autonomy** | Crash recovery rate | 0% (no resume) | 90%+ (checkpoint resume) |
| **2. Planning** | Phases adaptively activated mid-execution | 0 | 5+ dynamic triggers per engagement |
| **2. Planning** | Plan coverage report available | ❌ No | ✅ Yes, with coverage_gaps |
| **2. Planning** | LLM-refined plan with conditional branching | ❌ No | ✅ Yes |
| **3. Orchestration** | Tools with container isolation | 0 | All exploit/verification tools sandboxed |
| **3. Orchestration** | Tool health checks passing | ❌ Unknown | ✅ 100% registered tools verified |
| **4. Correlation** | Hypotheses generated per engagement | 0 (flag off) | 5+ average |
| **4. Correlation** | Cross-engagement trends available | ❌ No | ✅ Per-org trend dashboard |
| **5. Reporting** | PDF reports generated | ❌ No | ✅ Yes (via weasyprint) |
| **5. Reporting** | `argus report` CLI command | ❌ No | ✅ Yes |
| **5. Reporting** | Remediation verification | ❌ No | ✅ Yes, with before/after diff |

---

## Appendix: Key File Reference

| Goal | Key Files | Path |
|---|---|---|
| **1. Autonomy** | `dispatch_task.py`, `orchestrator_pkg/orchestrator.py`, `pipeline_router.py`, `intent_parser.py`, `state_machine.py`, `checkpoint_manager.py` | `argus-workers/` |
| **2. Planning** | `orchestrator_pkg/planning/adaptive_planner.py`, `agent/swarm.py`, `intelligence_engine.py`, `tools/workflow_intelligence_engine.py`, `phases.py` | `argus-workers/` |
| **3. Orchestration** | `tool_definitions.py`, `tool_core/registry.py`, `tools/tool_runner.py`, `tools/scope_validator.py`, `tool_core/sandbox.py`, `tools/mcp_bridge.py` | `argus-workers/` |
| **4. Correlation** | `attack_graph_db.py`, `tools/finding_correlation_engine.py`, `tools/attack_path_generator.py`, `tools/hypothesis_engine.py`, `llm_synthesizer.py`, `compliance_posture_scorer.py` | `argus-workers/` |
| **5. Reporting** | `orchestrator_pkg/reporting/report_generation_service.py`, `llm_report_generator.py`, `reporting/exporter.py`, `snapshot_manager.py`, `compliance_reporting.py` | `argus-workers/` |
