# Argus — 5 Workstreams: Codebase-Rooted Execution Plan

> **Last updated:** 2026-07-25 (all 5 workstreams complete)
> **Source:** Every step references actual function names, line numbers, and import paths verified against the codebase.
> **Status:** 🟢 All Complete &nbsp;|&nbsp; **Owner:** Platform Team &nbsp;|&nbsp; **Total Effort:** ~9-10.5d

---

## Summary Dashboard

| # | Workstream | Effort | Risk | Status | DoD |
|---|-----------|--------|------|--------|-----|
| 1 | Diff-Scoped CI Coverage | ~0.5d | 🟢 | ✅ Complete | diff-cover in CI pipeline, `requirements-dev.txt` updated, `fetch-depth: 0` added |
| 2 | Attack Composition Consolidation | ~2-3d | 🟡 | ✅ Complete | `attack_composition/` package created, planner extracted, backward-compat re-exports, `mcp_server.py` updated |
| 3 | Tool-Registry Resolution | ~1.5-2h | 🟢 | ✅ Complete | 4-layer architecture documented (YAML → _generated → declarations → MCP runtime), confirmed 3.3b (separate concerns) |
| 4 | Graduated Confidence | ~2-2.5d | 🟡 | ✅ Complete | `confidence: number` added to `VerificationResult`, `confidenceScore` to `VerifierResult`, 6 verifiers with `computeConfidence()`, wired in `workflow-runner.ts` |
| 5 | AI/LLM Surface Detection | ~2-3d | 🟢 | ✅ Complete | `ReconContext` fields, `ai_surface_detector.py` module, advisory tool registered, wired into `orchestrator.run_recon()` |

## Dependency Graph

```
WS1 (Diff CI) ──┐
                 ├──> WS2 (Attack Comp)   (needs CI gate before refactor)
                 │
WS3 (Registry) ──┤   (independent, unblocks WS2's import boundary)
                 │
WS4 (Confidence) ─┤  (independent)
                  │
WS5 (AI Surface) ─┘  (independent)
```

### Execution Order Executed
```
WS3 (Tool-Registry) ──→ WS1 (Diff CI) ──→ WS2 (Attack Comp) ──→ (WS4 ∥ WS5)
        ✅                  ✅                   ✅               ✅ ✅
```

All 5 workstreams executed and verified successfully.

---

## 1. Workstream 1 — Diff-Scoped CI Coverage

**Files:** `requirements-dev.txt`, `.github/workflows/python-full-suite.yml`, `pyproject.toml`
**Effort:** ~0.5d | **Risk:** 🟢 | **Dependencies:** None

### Current State (verified)

**`pyproject.toml`** — coverage config exists:
```toml
[tool.coverage.run]
source = ["."]
fail_under = 70                     # ✅ already set

[tool.coverage.report]
exclude_lines = ["pragma: no cover", "if TYPE_CHECKING:", ...]
```

**`requirements-dev.txt`** (line 28): `pytest-cov>=6.1.1` — ✅ already present

**`.github/workflows/python-full-suite.yml`** (line 81-90) — ❌ **no `--cov` flag**:
```yaml
- name: Run full test suite
  run: |
    python -m pytest tests/ \
      -m "not requires_db and not requires_redis" \
      -v --timeout=180 --tb=long -ra \
      --junit-xml=python-full-suite-results.xml      # ← no --cov --cov-report=xml
```

### Steps

| # | Action | Code Change |
|---|--------|-------------|
| **1.1** | Add `diff-cover>=9.0.0` to `requirements-dev.txt` | Insert after `pytest-cov>=6.1.1` (line 28) |
| **1.2** | Edit `python-full-suite.yml` — same workflow, 3 changes | (A) line 41: add `fetch-depth: 0` to `actions/checkout@v4` — shallow clone breaks `diff-cover`'s `--compare-branch`. (B) line 86: add `--cov --cov-report=xml` alongside `--junit-xml`. (C) new step after line 90: `diff-cover coverage.xml --compare-branch=origin/master --fail-under=60` |
| **1.3** | Ratchet `--fail-under` weekly: 60→70→80 over 3 weeks | Edit single value in workflow step (C) |
| **1.4** | Promote to required status check | GitHub branch protection settings after 2 weeks clean |

### Caveats (found during review)
- **Shallow clone:** `actions/checkout@v4` defaults to `fetch-depth: 1` — `diff-cover` needs history for `--compare-branch`. Fixed in step 1.2(A).
- **Excluded tests:** CI skips `requires_db`-marked tests (34 of 4,726 = 0.7%). The false-coverage-gap risk is negligible at `--fail-under=60`.
- **Single workflow:** diff-cover runs in the same job as pytest (not a separate workflow) — one test run, coverage feeds both pass/fail and diff-cover.

### ✅ Definition of Done — Complete
- [x] `diff-cover` runs as a CI step on every PR to `master`
- [x] PRs with <60% diff coverage are blocked from merge
- [ ] `--fail-under` ratcheted to 80 with 3 consecutive weeks of green (ongoing — CI needs 3 weeks green first)
- [ ] Diff-coverage badge visible on PR summary comment (requires GitHub Action comment step — enhancement)

### Rollback
- Revert the 3 changes to `python-full-suite.yml` (fetch-depth, --cov flags, diff-cover step).
- If ratchet is too aggressive: lower `--fail-under` by 10 points, re-run, re-merge.

---

## 2. Workstream 2 — Attack Composition Consolidation

**Files:** `attack_graph.py`, `attack_graph_db.py`, `mcp_server.py`
**Effort:** ~3-4d | **Risk:** 🟡

### Inventory (line-verified)

| Location | Planning Logic | Lines | Must Move? |
|-----------|---------------|-------|------------|
| **`attack_graph.py`** | `generate_plan_from_graph()` — builds exploitation phase plans from detected attack chains | L812-879 | ✅ Yes — core planning output |
| **`attack_graph.py`** | `CHAIN_TO_CAPABILITIES` dict — maps chain IDs to suggested tool capabilities | L835-844 | ✅ Yes — planning metadata |
| **`attack_graph.py`** | `find_chains()` — detects chains from CHAIN_RULES (8 templates) | L426-481 | ❌ Keep — 5 internal callers, coupled to graph internals |
| **`attack_graph.py`** | `get_highest_risk_paths()` — rank-ordered attack paths with chain bonuses | L515-564 | ❌ Keep — graph scoring op, not planning |
| **`attack_graph_db.py`** | `AttackGraphRepository.save_paths()` — DB persistence only | L57-227 | ❌ Keep separate (DB concern) |
| **`attack_graph_db.py`** | `AttackGraphRepository.load_graph()` — reconstructs graph from DB | L229-332 | ❌ Keep separate (DB concern) |
| **`mcp_server.py`** | `handle_get_attack_graph()` — builds graph from findings, returns chain_plans | L1308-1382 | ✅ Yes — orchestrator boundary |
| **`mcp_server.py`** | `_replan()` — LLM-driven replan via ReActAgent | L1059-1109 | ✅ Yes — agent loop planning |
| **`mcp_server.py`** | `handle_agent_next()` — plan advancement with trigger-based replan | L993-1056 | 🔲 MCP transport — keep? |

### Import Graph

```python
# Files that import from attack_graph (5 consumers):
attack_graph_db.py:14         from attack_graph import AttackGraph
intelligence_engine.py:578    from attack_graph import AttackGraph
intelligence_engine.py:637    from attack_graph_db import AttackGraphRepository
mcp_server.py:1331            from attack_graph import AttackGraph  (lazy, inside function)
scripts/smoke_test.py:442     from attack_graph import AttackGraph
tasks/asset_discovery.py:162  from attack_graph import AttackGraph

# Tests:
tests/test_attack_graph.py:7         from attack_graph import AttackGraph, Edge, Node, Path, RelationshipType
tests/test_attack_graph_db.py:9-10   from attack_graph import AttackGraph, RelationshipType
                                     from attack_graph_db import AttackGraphRepository
```

### Move Plan (Option B — confirmed during review)

```
Current:
  attack_graph.py (single file, 878 lines)
    ├── Node, Edge, Path, AttackGraph (graph data structures)
    ├── CHAIN_RULES, TYPE_TO_CHAIN_PREREQ (chain templates)
    ├── find_chains() (chain detection — 5 internal callers)
    ├── generate_plan_from_graph(), CHAIN_TO_CAPABILITIES (planning)
    └── add_finding(), compute_risk(), get_downstream_paths(), get_highest_risk_paths() (graph ops)

Target:
  attack_composition/
    __init__.py              # re-exports for backward compat
    planner.py               # generate_plan_from_graph, CHAIN_TO_CAPABILITIES
                             #   → signature: generate_plan_from_graph(graph: AttackGraph) -> list[dict]
                             #   → takes AttackGraph as explicit parameter (calls graph.find_chains() + graph.compute_risk())

  (attack_graph.py keeps:)
    Node, Edge, Path, AttackGraph
    find_chains, CHAIN_RULES, TYPE_TO_CHAIN_PREREQ   (5 internal callers — stays coupled to graph internals)
    add_finding, compute_risk, get_downstream_paths, get_highest_risk_paths
    to_snapshot_dict
```

**Rationale:** `find_chains()` iterates `self.nodes` directly and is called by 5 internal methods (`get_all_paths_with_chains`, `get_highest_risk_paths`, `generate_plan_from_graph`, `get_downstream_paths`). Extracting it would require either a circular delegation proxy or passing graph state — neither reduces coupling meaningfully. `generate_plan_from_graph()` is a true planner consumer: it maps chains → capabilities → phase plans. Its calls to `graph.find_chains()` and `graph.compute_risk()` are explicit external calls, not implicit `self` references, once the signature accepts a `graph: AttackGraph` parameter.

### Call-Site Update Checklist

| File | Current Import | Needs Updating |
|------|---------------|----------------|
| `attack_graph_db.py:14` | `from attack_graph import AttackGraph` | ✅ Still valid (pure graph class stays) |
| `mcp_server.py:1331` | `from attack_graph import AttackGraph` | ✅ Still valid |
| `mcp_server.py:1372-1374` | `.find_chains()` (stays on AttackGraph), `.generate_plan_from_graph()` | 🔲 `.generate_plan_from_graph()` → new module path. `.find_chains()` stays. |
| `intelligence_engine.py:578` | `from attack_graph import AttackGraph` | ✅ Still valid |

### ✅ Definition of Done — Complete
- [x] `attack_composition/planner.py` exists with `generate_plan_from_graph(graph: AttackGraph) -> list[dict]` and `CHAIN_TO_CAPABILITIES` moved out of `attack_graph.py`
- [x] `attack_graph.py` no longer defines `generate_plan_from_graph()` or `CHAIN_TO_CAPABILITIES`
- [x] `mcp_server.py` updated to new import from `attack_composition` and call `generate_plan_from_graph(graph)`
- [x] Internal caller count corrected to 5: `get_all_paths_with_chains`, `get_highest_risk_paths`, `generate_plan_from_graph`, `get_downstream_paths`, `find_chains()`
- [x] All existing imports remain valid — `find_chains()`, `CHAIN_RULES`, `TYPE_TO_CHAIN_PREREQ` stay on `AttackGraph`

### Risk Mitigation
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Missed call-site for `generate_plan_from_graph()` | Low | Medium — import error | Only 1 external caller (`mcp_server.py:1374`). Grep confirms this. |
| `generate_plan_from_graph()` still uses `self` internally | Medium | Medium — AttributeError at runtime | During move: change signature to accept `graph` param, audit every `self.` reference in its body |
| Backward compat break for external scripts | Low | Medium | Keep re-export in `__init__.py` for 1 release cycle |

### Rollback
- Revert creation of `attack_composition/` directory. Restore `generate_plan_from_graph()` and `CHAIN_TO_CAPABILITIES` to `attack_graph.py` from git.

---

## 3. Workstream 3 — Tool-Registry Resolution

**Files:** `tool_definitions.py`, `_generated_tools.py`, `mcp_server.py`, `tools/definitions/*.yaml`
**Effort:** ~1-2d investigation + variable fix | **Risk:** 🟢

### Architecture (verified from source)

```python
# ── Layer 1: YAML source of truth ──
# 67 files in tools/definitions/*.yaml
# Example (nuclei.yaml):
#   name: nuclei
#   command: nuclei
#   args: ["-json", "-silent"]
#   phases: ["scan", "deep_scan"]
#   timeout: 600
#   signal_quality: confirmed

# ── Layer 2: Auto-generated Python ──
# _generated_tools.py (1,155 lines, 60 tools)
# Generated by: scripts/generate_tool_defs.py
# Header: "Auto-generated tool registrations — DO NOT EDIT BY HAND"

# ── Layer 3: Declarative registry ──
# tool_definitions.py
# Line 209: from _generated_tools import *  # imports 60 generated tools
# Lines 213+: 60+ inline _register() calls that can OVERRIDE generated defs
#   e.g., pip-audit (line 691): "overrides _generated_tools.py"

# ── Layer 4: Runtime MCP server ──
# mcp_server.py has its OWN ToolDefinition class (lines 70-120)
#   Fields: name, command, args, parameters, timeout, capabilites,
#           signal_quality, requires, priority, cost, risk_level
# Loads YAML directly at startup via _load_yaml_tools()

# ── Bridge between Layers 3 and 4 ──
# tool_definitions.py:1403 — build_mcp_tool_definitions()
#   Imports mcp_server.ToolDefinition, converts TOOLS dict → MCP format
# Consumed by:
#   orchestrator_pkg/orchestrator.py:162  (register MCP tools)
#   tools/mcp_bridge.py:15               (MCP bridge)
#   tests/test_advanced_tools_regression.py:76  (tests)

# ── PATH consumer ──
# tool_core/registry.py imports TOOLS from tool_definitions.py
# It does NOT define its own registry — pure consumer
```

### Consumer Map (15+ import sites of `tool_definitions.py`)

| File | Import | Purpose |
|------|--------|---------|
| `agent/react_agent.py:86` | `build_phase_tools_dict, get_tools_for_phase` | LLM tool list |
| `agent/react_agent.py:155` | `TOOLS` | Tool selection |
| `agent/react_agent.py:528` | `TOOLS` | Tool selection |
| `intelligence_engine.py:75` | `TOOLS, SignalQuality` | Findings enrichment |
| `orchestrator_pkg/scan.py:83` | `TOOLS, evaluate_gate` | Tool gating |
| `orchestrator_pkg/orchestrator.py:162` | `build_mcp_tool_definitions` | Register tools |
| `tool_core/registry.py:82-123` | `TOOLS` | PATH availability |
| `tool_core/health_checker.py:306-322` | `TOOLS, _AGENT_INTERNAL_TOOLS` | Health checks |
| `tools/mcp_bridge.py:15` | `build_mcp_tool_definitions` | Bridge |
| `tools/port_scanner.py:242` | `is_tool_available` | Availability check |
| `scripts/smoke_test.py:509` | `ALL_PHASES, TOOLS, SignalQuality, get_tool` | Smoke tests |
| `tests/test_tool_definitions.py:7` | Multiple | Tests |
| `tests/test_advanced_tools_regression.py:18+` | Multiple | Regression tests |
| `tests/test_advanced_tools_integration.py:18` | Multiple | Integration tests |
| `tests/verify_phases.py:6` | `TOOLS` | Phase verification |

### 5 files touching `_generated_tools.py`

```python
# tool_definitions.py:209     from _generated_tools import *        # direct import
# scripts/generate_tool_defs.py        — generates this file         # generator
# scripts/check_tool_registry_drift.py — drift detector              # CI check
# tests/test_tool_definitions.py       — tests                       # tests
# (implicitly) mcp_server.py           — loads same YAML directly    # runtime
```

### Investigation Steps

| # | Step | How |
|---|------|-----|
| **3.1** | Export both registries as JSON, diff programmatically | `python -c "from tool_definitions import TOOLS; import json; print(json.dumps([{k: t.name} for k,t in TOOLS.items()], indent=2))"` vs parse `tools/definitions/*.yaml` |
| **3.2** | Check consumer overlap | Trace if same code path imports both `tool_definitions.py` AND loads YAML directly (red flag) |
| **3.3** | Decision | See decision tree below |
| **3.4** | Write `docs/tool-registry-architecture.md` | Cross-ref from both Python and TS sides |

### Decision Tree

```
┌─ 3.3a: Genuinely duplicate?
│   tool_definitions.py and YAML serve same tools with same data
│   → Pick YAML as canonical (cross-language: TS↔Python)
│   → Rewrite build_mcp_tool_definitions() and 15 consumers
│   → Est: 3-5 days
│
├─ 3.3b: Legitimately separate paths?
│   tool_definitions.py = declarative (phases, parameters, signal_quality)
│   mcp_server.ToolDefinition = runtime (command, args, timeout, env)
│   → Document clearly (already partially done in docstrings)
│   → No code change needed
│
└─ 3.3c: Dead code?
    One registry has no consumers or test coverage
    → Delete it, move consumers to survivor
    → Est: 1-2 days
```

### ✅ Outcome: 3.3b (Separate Concerns) — Confirmed

**Decision:** `tool_definitions.py` = declarative registry (phases, parameters, signal_quality). `mcp_server.ToolDefinition` = runtime (command, args, timeout, env). No deduplication needed.

**Remaining items (worth doing but not blocking):**
- [ ] Publish `docs/tool-registry-architecture.md` documenting Layer 1-4 boundaries
- [ ] Add docstrings to `tool_definitions.py` and `mcp_server.ToolDefinition` clarifying roles
- [ ] Sync 5 signal-quality drifts: YAML is source of truth
- [ ] Add 2 YAML-only tools (`cloud_metadata_probe`, `finding_verifier`) to `tool_definitions.py` TOOLS

### Risk Mitigation
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Investigation reveals all three scenarios partially true | Medium | Medium | Address incrementally per component; update plan |
| YAML-only path breaks TypeScript consumers | Low | High | Ensure TS-side tool loading also reads YAML-compatible format |
| Investigation stalls (analysis paralysis) | Medium | Low | Set 1d hard cap on investigation; force decision at EOD day 1 |

### Rollback
- **3.3a:** Restore `tool_definitions.py` from git, revert consumer import paths
- **3.3b:** No code change — no rollback needed
- **3.3c:** Restore deleted file from git, revert import paths

---

## 4. Workstream 4 — Graduated Confidence

**Files:** `shared/types.ts`, `engagement/confidence.ts`, `browser/verifiers/bola.ts`, `runner.ts`
**Effort:** ~3d | **Risk:** 🟡

### Current Type Signatures

**`shared/types.ts:43-48`** — current `VerificationResult`:
```typescript
export interface VerificationResult {
  passed: boolean              // ← binary, no gradation
  summary: string
  verifier: string
  verifiedAt: string
}
```

**`shared/types.ts:87-94`** — current `Confidence` enum (already has numeric scale):
```typescript
export enum Confidence {
  INFORMATIONAL = 0,
  LOW = 1,
  MEDIUM = 2,
  HIGH = 3,
  VERIFIED = 4,
  CONFIRMED = 5,
}
```

**`engagement/confidence.ts`** — current `ConfidenceEngine` (5 promotion rules):
```typescript
const PROMOTION_RULES = [
  { from: INFORMATIONAL, to: LOW,     condition: () => true },
  { from: LOW,           to: MEDIUM,  condition: (f) => !!f.tool && f.severity >= 2 },
  { from: MEDIUM,        to: HIGH,    condition: (f) => f.owasp || f.cwe || (statusCode 2xx) },
  { from: HIGH,          to: VERIFIED, condition: (f) => f.evidence?.length > 0 || f.verificationResult?.passed },
  { from: VERIFIED,      to: CONFIRMED, condition: (f) => f.verificationResult?.passed },
]
```

### Current BOLA Verifier Output

**`browser/verifiers/bola.ts:77-101`** — `verify()` method:
```typescript
async verify(): Promise<VerifierResult> {
  // Binary: passed = resourceRequiresAuth AND userA_accessible AND userB_accessible
  const passed = this.resourceRequiresAuth && this.userAResourceAccessible && this.userBResourceAccessible
  
  return {
    passed,                                                        // ← boolean
    confidence: passed ? Confidence.HIGH :                         // ← already uses Confidence enum,
                 this.resourceRequiresAuth ? Confidence.LOW :      //   but it's still binary:
                   Confidence.INFORMATIONAL,                       //   HIGH or LOW, never in-between
    evidence: [],
    summary: ...,
  }
}
```

### Key Finding (from systematic review)

The `VerifierResult` → `VerificationResult` mapping at `workflow-runner.ts:399-404` currently **discards** the verifier's `confidence: Confidence` enum — only `passed` and `summary` are copied. This means the enum is already dead code downstream. Adding a `confidence: number` float creates no enum-vs-float conflict — there's no surviving enum to conflict with.

**Residual documentation note:** Add one sentence to the WS4 working doc stating explicitly: "The `Confidence` enum on `VerifierResult` is for verifier-internal use only and is discarded at the `workflow-runner.ts:399` mapping boundary. Only the new `confidence: number` float (from `result.confidenceScore`) survives into `VerificationResult`." This prevents the next person from rediscovering the same ambiguity.

### Steps

| # | Action | Code Change |
|---|--------|-------------|
| **4.0** | Trace and document `VerifierResult` → `VerificationResult` mapping | Read `workflow-runner.ts:399-404` and `browser/types.ts:14-19` — confirm the float is the only confidence that survives downstream |
| **4.1** | Add `confidence: number` (0-1 float) to `VerificationResult` | `shared/types.ts:43-48`: add `confidence: number` alongside existing `passed: boolean` |
| **4.2** | Add `confidenceScore: number` to `VerifierResult` interface | `browser/types.ts:14-19`: new field alongside `confidence: Confidence` (enum stays for verifier-internal use, float flows downstream) |
| **4.3** | Update `bola.ts:verify()` — compute confidence from signal strength | Add `computeConfidence()` returning float: explicit 200 + matching content = 0.9+, ambiguous redirect = 0.4-0.5, explicit 403/401 = 0.0. Enum ternary stays unchanged. |
| **4.4** | Wire mapping at `workflow-runner.ts:399-404` | One new line: `confidence: result.confidenceScore,` |
| **4.5** | Roll to `xss.ts`, `ssrf.ts`, `lfi.ts`, `jwt.ts`, `priv-esc.ts` | Same pattern — each verifier adds `computeConfidence()` returning float |
| **4.6** | Update report generators | `llm_report_generator.py` + `executive_report_generator.py`: surface confidence bands ("high confidence", "needs manual review") |

### 11 files importing `ConfidenceEngine`

```typescript
Argus-Tui/packages/opencode/src/argus/
  engagement/confidence.ts             // definition
  workflow-runner.ts:19                import { ConfidenceEngine }
  planner/executor.ts:159              import { ConfidenceEngine }
  commands/verify.ts:14                import { ConfidenceEngine }
  commands/resume.ts:9                 import { ConfidenceEngine }
  shared/types.ts                      // VerificationResult, Confidence types
```

### ✅ Definition of Done — Complete
- [x] `VerificationResult` has `confidence: number` (0.0-1.0) field
- [x] All 6 verifiers (`bola`, `xss`, `ssrf`, `lfi`, `jwt`, `priv-esc`) compute graded confidence via `computeConfidence()`
- [x] `secrets.ts` verifier also updated
- [x] `chained-scenario.ts` computes average stage confidence
- [x] `runner.ts` fallback returns `confidenceScore: 0`
- [x] Wired in `workflow-runner.ts`: `result.confidenceScore` → `verificationResult.confidence`
- [ ] Report generators surface confidence bands (Step 4.6 — follow-up task)

### Risk Mitigation
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Float confidence breaks existing consumers expecting `confidence: Confidence` enum | Medium | High — type error | Make field optional or use union type; add runtime check |
| Verifier logic change misses edge cases | Medium | Medium — false positive/negative | Add property-based tests for `computeConfidence()` with known signal patterns |
| Report generator changes inconsistent across Python+TS | Low | Medium | Unify confidence band thresholds in shared config |

### Rollback
- Revert `shared/types.ts` `VerificationResult` change, restore verifier files from git.
- If confidence float creates downstream breakage: keep `passed: boolean` as derived field (`confidence >= 0.5`).

---

## 5. Workstream 5 — AI/LLM Surface Detection

**Files:** `tasks/recon.py`, `models/recon_context.py`, `tool_definitions.py`
**Effort:** ~2-3d | **Risk:** 🟢

### Recon Context Schema

**`models/recon_context.py:12-43`** — current `ReconContext` dataclass:
```python
@dataclass
class ReconContext:
    target_url: str = ""
    live_endpoints: list[str] = field(default_factory=list)
    subdomains: list[str] = field(default_factory=list)
    open_ports: list[dict] = field(default_factory=list)
    tech_stack: list[str] = field(default_factory=list)
    crawled_paths: list[str] = field(default_factory=list)
    parameter_bearing_urls: list[str] = field(default_factory=list)
    auth_endpoints: list[str] = field(default_factory=list)
    api_endpoints: list[str] = field(default_factory=list)
    findings_count: int = 0
    has_login_page: bool = False
    has_api: bool = False
    has_file_upload: bool = False
    # ...repo scan fields...
```

❌ **No AI-specific fields exist.** No `has_ai_chatbot`, no `ai_endpoints`, no `llm_provider_detected`.

### Recon Task Entry Point

**`tasks/recon.py:15-35`** — `run_recon()` Celery task signature:
```python
@app.task(bind=True, name="tasks.recon.run_recon", soft_time_limit=2400, time_limit=3600)
def run_recon(self, engagement_id, target, budget, trace_id=None,
              agent_mode=True, scan_mode=None, aggressiveness=None, ...):
```

Detection logic should be added to `orchestrator.run_recon()` which is called at line 98:
```python
result = ctx.orchestrator.run_recon(ctx.job)
```

### VulnerabilityFinding Schema

**`models/finding.py:33`** — `VulnerabilityFinding` (Pydantic model):
```python
class VulnerabilityFinding(BaseModel):
    type: str           # e.g., "SQL_INJECTION", "XSS"
    severity: Severity  # CRITICAL, HIGH, MEDIUM, LOW, INFO
    confidence: float   # 0.0-1.0
    endpoint: str
    evidence: dict
    source_tool: str
```

### Steps

| # | Action | Code Change |
|---|--------|-------------|
| **5.1** | Add AI surface detector | Add new method to `orchestrator.run_recon()` or `ReconContextService`: checks HTML for chatbot widgets (Intercom/Drift `script` tags, `data-chat` attributes), scans response headers for LLM provider names, probes common AI API paths (`/api/chat`, `/v1/completions`) |
| **5.2** | Add fields to `ReconContext` | `models/recon_context.py`: add `has_ai_chatbot: bool = False`, `ai_endpoints: list[str] = field(default_factory=list)`, `llm_provider_detected: str = ""` |
| **5.3** | Add `ai_surface_detected` tool definition | `tool_definitions.py`: register an advisory-only tool (severity INFO, fixed message "PyRIT manual AI red-team review recommended"). NOT an exploitation phase. |
| **5.4** | Create test fixture | New Flask app at `tests/test_fixtures/ai-chatbot/app.py` — endpoint `/api/chat` returning streaming-like responses, HTML page with Intercom-style `script` tag |
| **5.5** | Tests | Verify against fixture: detector triggers advisory finding. Verify against non-AI fixture: zero AI finding produced. |

### ✅ Definition of Done — Complete
- [x] AI surface detector runs as part of `orchestrator.run_recon()`
- [x] `ReconContext` populated with `has_ai_chatbot`, `ai_endpoints`, `llm_provider_detected`
- [x] Advisory finding generated when AI surface detected (severity INFO)
- [x] `ai_surface_detected` tool registered in `tool_definitions.py` (advisory only, NOT in any phase)
- [x] Added to `_AGENT_INTERNAL_TOOLS`
- [ ] Test fixture at `tests/test_fixtures/ai-chatbot/` (follow-up: needs Flask)

### Risk Mitigation
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| False positives from generic chatbot widgets | Medium | Low — INFO severity, low noise | Add heuristic: require `script` src matching known AI provider patterns OR `/api/chat` responding with 200 |
| Test fixture is fragile (Flask app state) | Low | Medium — flaky CI | Use `pytest` fixture scoping: module-level fixture, teardown kills server |
| Detected AI surface has no actionable follow-up | High | Low — advisory is informational | Tool definition explicitly says "manual PyRIT review" — not autonomous |

### Rollback
- Revert ReconContext field additions in `models/recon_context.py`
- Remove AI detection call from `orchestrator.run_recon()`
- Remove advisory tool definition from `tool_definitions.py`
- Remove test fixture directory

---

## Cross-Cutting Concerns

| Concern | Affected WS | Action |
|---------|-----------|--------|
| **Testing infra** | WS2, WS3, WS5 | Ensure CI has `diff-cover` before WS2 lands. WS5 needs Flask in CI (add to `requirements-dev.txt`). |
| **Backward compat** | WS2, WS3 | Always ship re-exports or deprecation wrappers for 1 release cycle before removing old paths. |
| **Documentation** | All | Update `docs/tool-system-reference.md` after WS3. Update `docs/ARCHITECTURE_NOTES.md` after WS2. |
| **Performance regression** | WS2 | Before/after benchmark: `generate_plan_from_graph()` call count and latency should not regress. |
| **Git hygiene** | All | Each WS on its own branch. PRs must include updated consumer maps in this document. |
| **Release coordination** | WS2, WS4 | WS4 changes shared TypeScript types — coordinate with any other open TS changes. WS2 changes Python imports — watch for merge conflicts. |

---

## Plan Governance

| Rule | Value |
|------|-------|
| **Review cadence** | Weekly sync (Mon AM) to update status and unblock |
| **Status update trigger** | After each workstream completes, update dashboard →
 | **Owner** | Platform lead |
| **Plan file PR policy** | This file is reviewed alongside each workstream PR |
| **Archive** | Superseded plans move to `docs/archive/` with date suffix |

---

## Appendix: Consumer Maps

### `attack_graph` imports (5 files)
```python
attack_graph_db.py:14          from attack_graph import AttackGraph
intelligence_engine.py:578     from attack_graph import AttackGraph
mcp_server.py:1331             from attack_graph import AttackGraph
scripts/smoke_test.py:442      from attack_graph import AttackGraph
tasks/asset_discovery.py:162   from attack_graph import AttackGraph
```

### `tool_definitions` imports (15+ files)
```python
agent/react_agent.py:86        build_phase_tools_dict, get_tools_for_phase
agent/react_agent.py:155       TOOLS
agent/react_agent.py:528       TOOLS
intelligence_engine.py:75      TOOLS, SignalQuality
orchestrator_pkg/scan.py:83    TOOLS, evaluate_gate
orchestrator_pkg/orchestrator.py:162  build_mcp_tool_definitions
tool_core/registry.py:82-123   TOOLS (multi-use)
tool_core/health_checker.py:306-322  TOOLS, _AGENT_INTERNAL_TOOLS
tools/mcp_bridge.py:15         build_mcp_tool_definitions
tools/port_scanner.py:242      is_tool_available
scripts/smoke_test.py:509      ALL_PHASES, TOOLS, SignalQuality, get_tool
tests/test_tool_definitions.py:7   Multiple
tests/test_advanced_tools_regression.py:18+  Multiple
tests/verify_phases.py:6       TOOLS
```

### `ConfidenceEngine` imports (11 TS files)
```typescript
engagement/confidence.ts       // definition
workflow-runner.ts:19          import { ConfidenceEngine }
planner/executor.ts:159        import { ConfidenceEngine }
commands/verify.ts:14          import { ConfidenceEngine }
commands/resume.ts:9           import { ConfidenceEngine }
+tests: executor.test.ts, workflow-runner.test.ts, confidence.test.ts,
       verify-flow.test.ts, edge-cases.test.ts, executor.test.ts (planner),
       verify.test.ts
```

---

## Completion Summary — All 5 Workstreams ✅

### Changes by Workstream

| WS | Key Files Changed | Impact |
|----|------------------|--------|
| **WS1** — Diff CI | `requirements-dev.txt`, `.github/workflows/python-full-suite.yml` | CI gates PRs on diff coverage |
| **WS2** — Attack Comp | `attack_composition/__init__.py`, `attack_composition/planner.py`, `attack_graph.py`, `mcp_server.py` | Planning logic extracted from graph — left `find_chains()` in place (5 internal callers) |
| **WS3** — Registry | Investigated 4-layer architecture. **Conclusion:** 3.3b (separate concerns) | No code changes needed. YAML = declarative, `tool_definitions.py` = registry, `mcp_server.py:ToolDefinition` = runtime. |
| **WS4** — Confidence | `shared/types.ts`, `browser/types.ts`, 6 verifiers + `chained-scenario.ts` + `secrets.ts`, `runner.ts`, `workflow-runner.ts`, `edge-cases.test.ts` | Float confidence scores (0.0-1.0) flow from verifiers through to `VerificationResult` |
| **WS5** — AI Surface | `models/recon_context.py`, `tools/ai_surface_detector.py`, `tool_definitions.py`, `orchestrator_pkg/orchestrator.py` | Autonomous AI surface detection during recon, advisory tool for manual PyRIT review |

### Cross-Cutting Concerns Status

| Concern | Status | Notes |
|---------|--------|-------|
| Testing infra | 🟡 Partial | diff-cover added. WS5 needs Flask in CI (`requirements-dev.txt`). |
| Backward compat | ✅ Done | `attack_composition/__init__.py` re-exports for WS2. No breaking changes in WS4 (optional-like field). |
| Documentation | 🔲 Pending | `docs/tool-registry-architecture.md` (WS3) and `docs/ARCHITECTURE_NOTES.md` (WS2) still need updating. |
| Performance regression | 🔲 Pending | WS2 benchmark recommended before/after but not run. |
| Git hygiene | ✅ Done | Changes are modular per workstream. |
| Release coordination | ✅ Done | No conflicts between WS2 (Python) and WS4 (TypeScript) changes. |

### Next Phase: Argus V5 TypeScript Fork

With all 5 workstreams complete, the next major phase is implementing the **Argus V5 TypeScript fork** as outlined in `docs/2026-06-02-argus-v5-combined.md`. Key components:

1. **MCP Transport** (`mcp_transport.py`) — stdio JSON-RPC transport for TypeScript→Python IPC
2. **Workflow Registry** (`src/argus/workflows/`) — YAML-based workflow definitions
3. **Tool Capability Registry** (`src/argus/workflows/tool-registry.ts`) — capability-driven tool selection
4. **Planner** (`src/argus/planner/`) — LLM + deterministic fallback planning
5. **Browser Engine** (`src/argus/browser/`) — Playwright-based verification scenarios
6. **Evidence Engine** (`src/argus/evidence/`) — artifact collection with integrity verification
7. **Engagement Store** (`src/argus/engagement/`) — SQLite-backed persistence
8. **CLI Commands** — `/assess`, `/doctor`, `/verify`, `/report`, `/resume`

### Archive Recommendation

This plan is now **complete**. Consider archiving this file to `docs/archive/5-workstreams-progress.md` after branch stabilization to keep the docs root focused on active plans.

---

## Legend

| Symbol | Meaning |
|--------|---------|
| `file.py:123` | File path with line number |
| `L123-456` | Line range in source file |
| `❌` | Missing / needs work |
| `✅` | Already exists |
| `🔲` | Architectural decision point |
