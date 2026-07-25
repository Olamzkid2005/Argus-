# Architecture Notes & Design Decisions

> **Purpose:** Record architectural decisions, confirmed intentional absences, and resolved investigations for the engineering team.
> **Last updated:** 2026-07-25

---

## 1. `pause_project` / Infra-Lifecycle — Intentionally Absent

**Status:** ✅ Confirmed absent by design

After an exhaustive codebase search, no `pause_project`, `infra_lifecycle`, or similar engagement-pausing functionality was found anywhere in the codebase.

### Rationale

The Argus engagement lifecycle is intentionally **fire-and-forget**:

| Phase | State | Description |
|-------|-------|-------------|
| `pending` | Initial | Engagement created, not yet started |
| `running` | Active | Orchestrator actively executing tools |
| `complete` | Terminal | All phases completed successfully |
| `failed`  | Terminal | Fatal error during execution |

There is intentionally **no `paused` state** for the full engagement lifecycle because:

1. **Tool externalities:** Most security tools (nuclei, sqlmap, dalfox) do not support pausing mid-execution. Killing and resuming them would lose state.
2. **Checkpoint-based resume:** Instead of pausing, Argus uses per-tool-call checkpointing (`checkpoint_manager.py`). Completed tools are skipped on resume. This is more reliable than process-level suspension.
3. **Cost control:** LLM budget tracking (`LlmCostTracker`, `governance.py`) handles cost limits by preventing new LLM calls — no need to pause the engagement.
4. **Simplicity:** Eliminates an entire category of edge cases (what happens if a tool completes during pause? does the orchestrator heartbeat while paused? etc.)

### If pause were needed

If a future requirement demands engagement pausing, the implementation should:

1. Add a `paused` state to `EngagementStateMachine` in `state_machine.py`
2. Add `pause_engagement` / `resume_engagement` endpoints to the orchestrator
3. After resume, use existing `checkpoint_manager.get_resume_plan()` to determine which tools need re-execution
4. Cap paused duration (e.g., 24h auto-resume or auto-fail) to prevent abandoned paused engagements

---

## 2. Slash-Command Bleed — No Vulnerability Found

**Status:** ❌ Refuted — no evidence of slash-command bleed vulnerability

### Investigation

The audit item "Verify the slash-command bleed fix actually landed" was investigated across the entire TUI codebase.

**What was examined:**

- `Argus-Tui/packages/opencode/src/argus/intent-classifier.ts` — Classifies user input. Slash commands (`/scan`, `/assess`, `/recon`, etc.) are detected via `classifyIntent()` which checks for leading `/` and maps to the `ArgusCommandRouter`. Non-slash-command input flows to natural language processing. No bleed path exists.
- `Argus-Tui/packages/opencode/src/argus/tui-commands.ts` — Defines `ArgusTuiCommands` and `findArgusTuiCommand()`. Commands are explicitly enumerated; there is no fallback that could interpret non-command input as a command.
- `Argus-Tui/packages/opencode/src/argus/agent.ts` — `ArgusCommandRouter` handles slash commands distinctly from tool execution. Commands like `/status`, `/doctor` have separate handler paths.
- `Argus-Tui/packages/opencode/src/project/project.ts` — The `/init` slash command subscription is isolated to a per-instance handler.

**Conclusion:** The slash-command classification is strict — a leading `/` is required, and the command must match an enumerated list. There is no path where natural language input could be misinterpreted as a slash command, or where user input from one context (e.g., a chat message) could bleed into another context's command processing.

### Note on the original claim

The original claim that a "slash-command bleed fix" needed to "land" may refer to a pre-audit state that has since been resolved by the `intent-classifier.ts` implementation (which is the current codebase state). No remnant of a bleed vulnerability was found.

---

## 3. Subprocess Sandbox Isolation — Future Work

**Status:** 🔍 Documented gap — see `docs/sandbox-isolation-plan.md`

The `chain_exploit_generator.py` uses `subprocess.run()` with `shell=False` and a locked-down environment (blocked env vars) for verifying chain exploit scripts. This is adequate for the current threat model but could be hardened with Docker container isolation. See the sandbox isolation plan document for the full design.

---

## 4. Thread Safety Model

The DI container (`di_container.py`) uses:

- **Module-level lock** (`_containers_lock`): Protects the global `_containers` dict
- **Per-container lock** (`self._lock`): Double-checked locking on lazy-init properties (`tool_runner`, `llm_client`, `checkpoint_manager`)
- **Closed guard** (`self._closed`): Prevents use of a closed container

This model supports concurrent access across engagements while preventing data races.

---

## 5. LLM Data Sanitization Architecture

The `_sanitize_for_llm()` function in `agent_prompts.py` is the **single entry point** for all external data entering LLM context. It applies:

1. **Truncation** to 3000 chars (limits context window abuse)
2. **Control character stripping** (prevents ANSI escape injection)
3. **Backtick fence replacement** (` ``` ` → `` ` ` ` ``) — prevents prompt structure breakage
4. **Prompt injection pattern redaction** — regex-based, 8 patterns covering system prompt overrides, command injections, and tool execution attempts
5. **Secret/credential redaction** — 40+ patterns covering API keys, tokens, passwords, private keys, database URLs, cloud credentials

**Known limitation:** Regex-based defenses are bypassable by novel phrasing. See `test_sanitize_for_llm_adversarial.py` for adversarial test vectors.

---

## 6. Diff-Scoped CI Coverage (WS1)

**Status:** ✅ Complete — 2026-07-25

### What Changed

Added `diff-cover` to the CI pipeline to enforce diff-level code coverage on every PR to `master`.

### Files Modified

- `argus-workers/requirements-dev.txt` — added `diff-cover>=9.0.0`
- `.github/workflows/python-full-suite.yml`:
  - Added `fetch-depth: 0` to `actions/checkout@v4` (shallow clone breaks diff-cover)
  - Added `--cov --cov-report=xml` to pytest invocation
  - Added `diff-cover coverage.xml --compare-branch=origin/master --fail-under=60` step

### Design

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `--fail-under` | 60 (initial) | Ratcheted to 80 over 3 weeks |
| `--compare-branch` | `origin/master` | Diffs against master |
| Test filter | `not requires_db and not requires_redis` | 34 of 4,726 tests excluded (0.7%) |

---

## 7. Attack Composition Consolidation (WS2)

**Status:** ✅ Complete — 2026-07-25

### What Changed

The `generate_plan_from_graph()` method and `CHAIN_TO_CAPABILITIES` dict were extracted from `attack_graph.py` into a dedicated `attack_composition/` package:

```
attack_composition/
  __init__.py      # backward-compatible re-exports
  planner.py       # generate_plan_from_graph(graph) + CHAIN_TO_CAPABILITIES
```

### Rationale

`attack_graph.py` had two concerns mixed in one class:
- **Graph operations**: `add_finding()`, `find_chains()`, `compute_risk()`, `get_highest_risk_paths()` — these operate on the graph's internal nodes/edges and are tightly coupled to the AttackGraph class
- **Planning output**: `generate_plan_from_graph()` maps detected chains → capabilities → phase plans — this is a consumer of the graph, not an internal operation

By extracting planning into its own package, `generate_plan_from_graph()` can be tested independently and consumers (like `mcp_server.py`) import it without importing the entire graph class.

### What Stayed in attack_graph.py

- `Node`, `Edge`, `Path`, `AttackGraph` — core data structures
- `find_chains()` — 5 internal callers, tightly coupled to graph internals
- `CHAIN_RULES`, `TYPE_TO_CHAIN_PREREQ` — chain templates used by internal methods
- `get_highest_risk_paths()`, `get_downstream_paths()` — graph scoring operations

### Call-sites Updated

- `mcp_server.py:1372-1374` — changed `graph.generate_plan_from_graph()` → `generate_plan_from_graph(graph)`
- All other `attack_graph` imports (5 external callers) remain valid since the core API surface is unchanged

---

## 8. Graduated Confidence (WS4)

**Status:** ✅ Complete — 2026-07-25

### What Changed

Added float-based confidence scores (0.0-1.0) alongside the existing `Confidence` enum (0-5), enabling graded confidence instead of binary pass/fail.

### Type Changes

| Type | New Field | Purpose |
|------|-----------|---------|
| `VerificationResult` (`shared/types.ts`) | `confidence: number` | 0.0-1.0 float from the verifier — survives downstream |
| `VerifierResult` (`browser/types.ts`) | `confidenceScore: number` | 0.0-1.0 float from `computeConfidence()` — mapped to `VerificationResult.confidence` |

### Verifier computeConfidence() Methods

| Verifier | Confidence Logic |
|----------|-----------------|
| **bola.ts** | BOLA confirmed: 0.85, auth works: 0.3, no auth: 0.0 |
| **xss.ts** | Payload executed: 0.9, not: 0.0 |
| **ssrf.ts** | Metadata reachable: 0.95, internal leak: 0.8, general response: 0.65 |
| **lfi.ts** | File content w/ 200: 0.9, non-200: 0.5, not detected: 0.0 |
| **jwt.ts** | alg:none accepted: 0.95, payload tamper: 0.7, rejected: 0.0 |
| **priv-esc.ts** | Escalation w/ 200: 0.85, without 200: 0.5 |
| **secrets.ts** | High-conf patterns: 0.9, medium/low: 0.4 |
| **chained-scenario.ts** | Average of stages, boosted if all pass |

### Mapping Boundary

In `workflow-runner.ts`, `result.confidenceScore` is mapped to `verificationResult.confidence`. The `Confidence` enum on `VerifierResult` is for verifier-internal use only and is discarded at this boundary.

### Files Updated

- `shared/types.ts` — `VerificationResult` interface
- `browser/types.ts` — `VerifierResult` interface
- 6 verifiers + `chained-scenario.ts` + `secrets.ts` — `computeConfidence()` methods
- `runner.ts` — error fallback with `confidenceScore: 0`
- `workflow-runner.ts` — mapping line
- `Argus-Tui/packages/opencode/test/argus/regression/edge-cases.test.ts` — mock objects updated

---

## 9. AI/LLM Surface Detection (WS5)

**Status:** ✅ Complete — 2026-07-25

### What Changed

Added autonomous detection of AI/LLM components during the reconnaissance phase. The detector scans HTML for chatbot widgets (Intercom, Drift, Zendesk, Crisp, Tawk, LiveChat, Freshchat, Olark), checks response headers for LLM provider signatures, and probes API endpoints for known AI paths (`/api/chat`, `/v1/completions`, etc.).

### New Files

| File | Purpose |
|------|---------|
| `tools/ai_surface_detector.py` | Detection logic: `detect_ai_surface()` updates ReconContext in place; `build_ai_advisory_finding()` generates INFO-severity advisory finding |
| `test_fixtures/ai-chatbot/app.py` | Flask test fixture with Intercom-style widget HTML + `/api/chat` + `/api/v1/completions` endpoints |
| `tests/test_ai_surface_detector.py` | 16 tests (14 unit, 2 E2E gated behind `RUN_E2E_TESTS=1`) |

### ReconContext Fields Added

- `has_ai_chatbot: bool = False` — set when any AI surface indicator is found
- `ai_endpoints: list[str] = field(default_factory=list)` — discovered AI API paths
- `llm_provider_detected: str = ""` — detected provider name (openai, anthropic, intercom, etc.)

### Detection Categories

1. **Chatbot widgets** — script tag patterns matching 8 known providers
2. **LLM provider headers** — response headers (e.g., `x-request-id`, `openai-`)
3. **AI API paths** — `/api/chat`, `/v1/completions`, etc. matched against `ReconContext.api_endpoints`
4. **Content patterns** — ChatGPT, GPT, Claude, etc. in page HTML

### Advisory Finding

When AI surface is detected, an INFO-severity advisory finding is generated recommending manual PyRIT review. The finding includes the detected provider, endpoints, and remediation guidance for prompt injection, data leakage, and insecure LLM access controls.

### Integration

The detector is called from `orchestrator.run_recon()` after the recon pipeline completes. If AI surface is detected, the advisory finding is appended to the findings list. The advisory tool `ai_surface_detected` is registered in `tool_definitions.py` (no exploitation phases — advisory only).

---

## 10. Tool Registry Architecture (WS3)

**Status:** ✅ Documented — see `docs/tool-registry-architecture.md`

The 4-layer tool registry architecture was investigated and documented. See the dedicated document for full details. Key finding: the four layers serve legitimate different purposes and should remain separate (Outcome 3.3b — Legitimately Separate Paths).
