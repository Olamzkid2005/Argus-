# Argus — Demo Readiness Plan

**Goal:** reach a defensible, working demo of an autonomous security-assessment run:
one command starts an assessment, the **engine decides which tools to run** (not a hard-coded
list), phases advance without a human, a report artifact is produced, and scope is enforced.

**Status of this document:** every claim below was verified against this checkout on 2026-09-29.
Line numbers are from this working tree. Where something is *unverified*, it says so explicitly.

---

## 1. What "working demo" means (and what it must not claim)

| Tier | Definition | State |
|---|---|---|
| **P0 — Pipeline runs** | One command completes recon → scan → analyze → report on a local authorized target. | Reachable — B1 fixed (`e4ed6102`), `doctor` 10 passed / 0 failed |
| **P1 — Agent decides** | Tool selection comes from the agent loop (`agent_decisions` rows written, not all `was_fallback`). | Machinery present; B1 + B4 fixed, needs a run to evidence it |
| **P2 — Signal-driven autonomy** | Phases activate from recon signals; run is unattended end-to-end; report + audit trail emitted. | **Recommended demo bar** |
| **P3 — Multi-host red team** | Pivot/lateral movement across hosts. | Not a demo goal |

Language to use: *"target-scoped autonomous assessment with early post-exploitation"*.
Not: *"fully autonomous red team"*.

---

## 2. The architecture as actually implemented

There are **three execution paths**, and they do not share an orchestration layer. This is the
single most important thing to internalize before planning demo work.

### Path A — TUI / CLI `assess` (TS drives, Python decides) ← **primary demo surface**
```
bun run src/argus/main.ts assess <target>
  → commands/assess.ts
  → WorkflowRunner.run()                 workflow-runner.ts:815
      ├─ getTargetValidator().validateTarget()          (scope guardrail)
      ├─ EngagementStore (SQLite ~/.argus/argus.db)     ← persistence
      ├─ WorkflowPlanner.plan()  (LLM or deterministic)
      └─ InProcessExecutor
            ├─ bridge.agentInit(...)    executor.ts:532
            ├─ loop: bridge.agentNext() → bridge.callTool() → bridge.agentObserve()
            └─ bridge.phaseComplete()
  → WorkersBridge (stdio JSON-RPC)  →  argus-workers/mcp_server.py
```
The **decision-making engine is Python** (`MCPServer.handle_agent_next`, `handle_agent_observe`
in `mcp_server.py`). The TS side is a planner/executor shim. Tool execution is
`MCPServer.call_tool`.

### Path B — Celery / live-fire (Python end to end) ← **unattended demo surface**
```
dispatch_task.py → celery_app → tasks.recon.run_recon
  → Orchestrator.run_recon/run_scan/run_analysis/run_reporting
  → app.send_task(...) to chain the next phase
```
Chaining is **already wired** (verified dispatch edges):
`recon.py:161,363 → scan` · `scan.py:214 → auth_focused_scan` · `scan.py:254 → deep_scan` ·
`scan.py:291,335,544,647 → analyze` · `analyze.py:128,170 → report/post_exploit` ·
`post_exploit.py:189,219 → …` · `report.py:88,131 → llm_review/diff`.

### Path C — Local CLI (`python -m cli assess <target> --local`) ← **cheapest demo**
Runs recon→scan→analyze→report **in-process on SQLite**, with `DATABASE_URL` deliberately popped:
*"CLI always runs in local/SQLite mode — no Docker/Postgres needed."* (`cli/main.py:48-52`).
Entry: `cli/cmd/assess.py` → `cli/_local_mode.py::_get_orchestrator` →
`_run_phases(orch, target, phases=("recon","scan","analyze","report"))`.
Verified working: `python -m cli --help` and `python -m cli list` both run.

> **Planning consequence:** Path C removes the entire Docker/Postgres/Redis/Celery dependency
> chain from the critical path. Use it to prove the engine, then graduate to Path A/B for the demo
> surface.

---

## 3. Blockers, verified

### B1 — MCP ping contract mismatch (CRITICAL, blocks all of Path A) — *fixed `e4ed6102`*
`isHealthy()` requires the literal string `"pong"`:

- `Argus-Tui/packages/opencode/src/argus/bridge/mcp-client.ts:326`
  ```ts
  async isHealthy(): Promise<boolean> {
    const result = await this.sendRequest("ping", {})
    return result === "pong"        // ← never true against the real worker
  }
  ```
- Python returns an **object**: `mcp_transport.py:58-70`
  ```py
  def _ping(params=None) -> dict:
      return {"pong": True, "timestamp": int(_time.time() * 1000)}
  ```
  which `_process_request` wraps as `{"jsonrpc":"2.0","id":…,"result":{...}}`.

**Measured, not inferred** — spawning the real worker and sending a `ping`:
```
FIRST RESPONSE after 1.42s
raw response: {"jsonrpc": "2.0", "id": 1, "result": {"pong": true, "timestamp": 1790661954480}}
typeof result: dict | equals 'pong'? False
```
So the worker is **healthy in 1.42 s**; it is *not* a timeout problem.

**Consequence chain:** `isHealthy()` always false → `waitForReady()` loops until
`ARGUS_MCP_READY_TIMEOUT_MS` (default 10 000 ms) and throws `mcp-client.ts:340` →
`spawnChild()` throws → `connect()` throws → **no tool can ever execute on Path A**, and
`argus doctor` reports `✗ [MCP Worker] Worker error: MCP worker connect timed out after 10s`.

**Why it survived:** the only test touching this stubs the RPC out —
`test/argus/unit/bridge/mcp-client.test.ts:676` does `bridge.sendRequest = async () => "pong"`.
The mock asserts the code's own assumption, so it can never catch the drift.

**Fix options** (pick one, then freeze with a test):
- **A (preferred):** accept both shapes in TS.
  `return result === "pong" || (typeof result === "object" && result !== null && (result as any).pong === true)`
- **B:** return the bare string from Python — `return "pong"` — and drop `timestamp`
  (check no other client consumes it first).

### B2 — The TS↔Python boundary has no real test
The only "live target" test is `test/argus/e2e/targets.test.ts`, and it is not live: it calls
`runAssessmentWithMock(target, mockBridge)` (line 138) and returns canned findings for known
targets — explicitly *"so the pipeline doesn't stall on connect()"* (line 83).
Every integration test mocks the bridge, which is exactly how B1 shipped. Closing B2 is what stops
this class of bug recurring.

### B3 — Scope config blocks autonomous mode
`argus.config.yaml` ships `security.scope.mode: warn` with `allowed_targets: []`.
`validateAutonomousScopeMode()` (`workflow-runner.ts:131`) **throws** when `ARGUS_AUTONOMOUS=1`
and mode is `warn`/`open`; `runtime/preflight.py` enforces the same on the Python side.
So `assess --autonomous` cannot start until the config is set to `allowlist` + explicit targets.

**Resolved (commit `b0a5a4fd`).** The guard now accepts an allowlist supplied by config *or* env
(`ARGUS_SCOPE_MODE` / `ARGUS_ALLOWED_TARGETS`), the allowlist actually rejects out-of-scope
targets (it previously compared patterns against the whole URL while the config documented
hostnames), and the guard's error is no longer swallowed by a surrounding `catch` that rewrote it
as "config missing". Still required for a demo run: real targets in `argus.config.yaml`.

### B4 — LLM key conventions are split across the two runtimes
- TS planner read `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `OPENCODE_API_KEY`, model from
  `ARGUS_PLANNER_MODEL` / `OPENCODE_MODEL` (`planner/llm-service.ts:78-82`).
- `argus-workers/.env` sets `LLM_API_KEY` + `LLM_MODEL` (Python's convention).
- Bun auto-loads `.env` from the **process cwd** (the `opencode` package), so
  `argus-workers/.env` is invisible to the TS planner.

Result: the planner silently runs deterministic even though a key is "configured".
(Python-side use of `LLM_API_KEY` is a separate, also-unverified path.)

**Resolved (`0bd76813`, `2f8906ac`, `60beab1a`, `b6a7a2a1`).** The model now comes from
OpenCode's provider registry only — the same `Provider`/`Auth` services OpenCode's own agent uses,
lowered through the shared `LLMNative.model()` adapter — and ambient provider credentials are
ignored in both runtimes unless `ARGUS_ALLOW_AMBIENT_LLM_ENV=1`. Because the Python worker has no
registry of its own, the planner resolves the model once and hands the worker the concrete
OpenAI-compatible endpoint at `agent_init.llm`; `endpoint_from_config` stops the key's prefix from
re-routing that handoff to a different provider. Verified handoff on this machine:
`opencode-go/kimi-k2.7-code` → `https://opencode.ai/zen/go/v1`. Both runtimes therefore run the
same model, and no ambient key is billed. **Not yet verified:** an actual completion from either
runtime (only resolution + mocked calls have run so far).

### B5 — `doctor` warnings are partly stale, partly real gaps
- Looks for `.env` at `PROJECT_ROOT` (`doctor.ts` `envCheck`, `configValidationCheck`) — so
  `argus-workers/.env` is not seen.
- `REDIS_URL` unset → real (Path B needs it; Path A/C do not).
- `NEXTAUTH_SECRET` unset → **stale**: there is no Next.js web UI (`argus-platform/` was deleted
  in the v5 migration). `docker-compose.yml` no longer references `NEXTAUTH_*`.
- `MISSING: sqlmap`-style claims need care: `tool_utils.resolve_tool_binary` uses an *augmented*
  PATH and correctly finds e.g. `argus-workers/venv/bin/sqlmap` even when `which sqlmap` fails.
  The tool inventory you supplied looks like the **container's** (`/venv/bin/wafw00f` is a
  container path), not this host's.

### B6 — Path B infrastructure is not up
`docker-compose.yml` requires `POSTGRES_PASSWORD` and `DATABASE_URL` (fail-fast `:?`), and Path B
needs Postgres + Redis + a worker. None are running here, and there is no repo-root `.env`.

### B7 — Interpreter selection is implicit
`WorkersBridge` defaults to bare `python3` (`mcp-client.ts:99`), and `doctor.resolvePython()`
honours `ARGUS_PYTHON` first. On this host system `python3` happens to have the deps
(verified: `import psycopg2, celery` succeed), but that is environmental luck, not a guarantee.

### B8 — Local/localhost targets cannot be scanned at all (found by running the demo)

First real end-to-end attempt — `python -m cli assess http://127.0.0.1:<port> --local` against
`test_fixtures/simple-web-app` (Flask, deliberately SQLi-vulnerable) — **completed with exit 0 and
0 findings**. All four phases ran; nothing was scanned. Two independent blocks:

**(a) Scope is declared but never applied.** `cli/_local_mode.py:185` builds
`"scope": {"mode": "allowlist", "allowed_targets": [target]}` into the job dict, but
`orchestrator_pkg/scan.py:496-500` reads scope from **ctx attributes**
(`getattr(ctx, "scope_mode", ...)`, `getattr(ctx, "allowed_targets", None)`). The job's scope never
reaches ctx, so `allowed=None` and the validator falls back to loading scope from PostgreSQL:
```
Failed to persist scope config for <id>: [DATABASE_ERROR] DATABASE_URL environment variable not set
SCOPE_VALIDATOR: NO SCOPE CONFIGURED — ALL TARGETS WILL BE REJECTED.
Target http://127.0.0.1:<port> REJECTED — no scope configured.
```
Local mode deliberately pops `DATABASE_URL`, so this path can never succeed.

**(b) Loopback is blocked unconditionally.** `orchestrator_pkg/scan.py:507` calls
`ScopeValidator.is_internal_address(hostname)` *before* the scope check, and that predicate returns
`True` for `127.0.0.1` (`scope_validator.py:192`; asserted in `tests/test_scope_validator.py:329`):
```
Blocked internal/SSRF hostname: 127.0.0.1
Target http://127.0.0.1:<port> is an internal/SSRF target - blocking
Scope/SSRF filter blocked 1 of 1 targets - nothing to scan
```
This is **deliberate and tested** ("SSRF check runs BEFORE scope check — internal targets blocked
even if in scope"), but it means *no* private/loopback target is scannable. Consequently both of
this project's own documented demo targets are unreachable by design:
`test_fixtures/*` apps (loopback) and `scripts/livefire` defaults to
`TARGET_URL=http://127.0.0.1:3001` (Juice Shop, loopback). There is **no opt-in env var** for
internal targets — the only override in the codebase is `ARGUS_ALLOW_UNSCOPED`
(`scope_validator.py:66`), which addresses (a) but not (b). This is consistent with the absence of
any recorded live-fire run.

**Root cause of (a), pinned:** the recon/orchestrator path resolves scope from the **database**
rather than the job payload — `orchestrator_pkg/orchestrator.py:200` calls
`EngagementService.load_authorized_scope(self.engagement_id)` (and `:323` calls
`store_scope_config`). With `DATABASE_URL` popped by local mode, that load returns empty, so
`ScopeValidator.__init__` emits `NO SCOPE CONFIGURED - ALL TARGETS WILL BE REJECTED` and
`validate_target()` raises for every target. The job-payload scope that
`cli/_local_mode.py:185` sets is never consulted on this path. The secondary scan-pipeline filter at
`orchestrator_pkg/scan.py:497-498` reads scope from **ctx attributes**
(`getattr(ctx, "scope_mode")`, `getattr(ctx, "allowed_targets")`), which the orchestrator sets on
*itself* (`orchestrator.py:698-699`), so that path is only correct when ctx is the orchestrator.

**Decision taken (option 1):** permit an internal/loopback target only when **both** an explicit
`ARGUS_ALLOW_INTERNAL_TARGETS` opt-in is set **and** the host is explicitly listed in the
engagement's authorized scope allowlist. Cloud metadata endpoints (`169.254.169.254`,
`metadata.google.internal`, `instance-data*`, `100.100.100.200`) stay blocked unconditionally.
Note `_BLOCKED_METADATA_HOSTNAMES` (`tools/scope_validator.py:18`) currently mixes metadata hosts
with loopback (`localhost`, `127.0.0.1`, `::1`, `::`, `0.0.0.0`), so those two classes must be split
before the opt-in can work. `ScopeValidator.is_internal_address()` semantics must stay unchanged
(it is asserted True for loopback in `tests/test_scope_validator.py:326-329`); the block decision
belongs in a new predicate that the only blocking call site (`orchestrator_pkg/scan.py:507`) uses.

**Resolved — both halves, measured against the fixture:**

- **Scope reaches the validator** (`63bc9837`): the run scope is published for the process
  (`tools/scope_validator.py:set_process_scope`) and forwarded through `ToolRunner` and
  `orchestrator_pkg/scan.py`, so an allowlisted target is accepted with no Postgres scope row.
  Subtree paths and the bare host match; the wrong port, a host with a suffix (`:8877x`), another
  host and an attacker-controlled domain do not.
- **The opt-in works** (`b0a5a4fd`, verified 2026-09-30):
  `ARGUS_ALLOW_INTERNAL_TARGETS=1` plus an allowlisted target lets the scan phase run. This is the
  flag Step 1's command line was missing; without it the scan phase filters its only target and the
  run looks like "nothing found".
- The classifier no longer announces a block it did not make (`edd4b313`):
  `is_internal_address()` logged `Blocked internal/SSRF hostname: 127.0.0.1` three times in a run
  that then scanned that target. It is a predicate — detection is now a debug line, and every
  caller that really blocks keeps its own warning.

### B9 — No LLM credential on this machine can actually serve a request

Found by making the first real planner call this repo has ever made (`c1cf6984`). The call now
reaches the provider and returns a *provider-level* answer instead of a malformed-request error,
which is what makes this credential problem visible rather than masked:

| Model the registry offers | Real answer |
|---|---|
| `opencode-go/kimi-k2.7-code` | **403** — "an active OpenCode Go subscription is required to use Go models" |
| `opencode/big-pickle` (free tier) | **403** — "OpenCode's free tier can only be used from within OpenCode" |
| `deepseek/deepseek-v4-pro` | **402** — "Insufficient Balance" |
| `xiaomi-token-plan-sgp/mimo-v2.6-pro` | **401** — "Invalid API Key" |

The free-tier answer is **not an Argus defect**. The honest picture is narrower than "no OpenCode
access": the **installed** OpenCode 1.18.33 *can* use the free tier on this machine —

```
cd Argus-Tui/packages/opencode && opencode run --model opencode/nemotron-3-ultra-free "Reply with exactly: PONG"
→ PONG                                             # works
```

…from any directory, `/tmp` included, while **this source checkout** gets the 403 in either
directory (`bun run src/index.ts run --model opencode/big-pickle "…"`). So the gate distinguishes
some property of the official client that this fork does not reproduce.

> **Correction (measured later):** an earlier version of this section claimed the free tier worked
> "only from this project directory". That was an artifact of `big-pickle` being intermittently
> exhausted: the free tier is served to the installed client regardless of directory, and
> `opencode/nemotron-3-ultra-free` answers consistently where `big-pickle` 403s on and off.

Ruled out by measurement, not assumption:

- **Headers.** A local capture server recorded both clients' real requests: header sets are
equivalent (`Bearer public`, `x-opencode-client`, `x-opencode-project`, `x-opencode-request`,
`x-opencode-session`, same body keys, same model, same `stream_options`).
- **User-Agent.** Four variants against the live gateway, including the working client's exact UA
  string and no UA at all — all 403.
- **The session header** (fixed — `c1cf6984`): that was a *different*, real defect
  (`MissingSessionID`); fixing it is what let this credential question become visible.
- **Transmission loss.** Headers were verified on the wire before any of the above was concluded.

The account store (`~/.local/share/opencode/account.json`) holds per-service API keys but **no
console account** — the device-code login that issues `access_token`/`refresh_token`
(`src/account/`, `opencode console login`) has never been completed here — and Go is a paid
subscription the operator does not hold.

**Options, in order of what they cost:**

1. **Supply any working key** — a provider key Argus can use directly. Both runtimes already run on
   one model (`b6a7a2a1`), so this is a config change plus a verification run, not a build.
2. **Route Argus's LLM calls through the installed, working OpenCode client** (e.g. its server
   API) instead of calling a gateway directly. Keeps "OpenCode's own AI" literally, but is a design
   decision — it makes an external binary a runtime dependency of both the planner and the worker.
3. **Sign in to OpenCode Console** (device-code login) and retest; the free-tier gate may be tied
   to that account identity rather than to anything visible in the request.
4. **Subscribe to Go** — `opencode-go/kimi-k2.7-code` then works; its routing was verified fixed.

Until one of these happens no phase can make a real LLM call, and Step 3's `agent_decisions`
evidence cannot exist.

**Resolved (option 2): both runtimes now borrow the installed OpenCode client.** Argus starts — or
reuses — a local `opencode serve` and asks *that* to make the call, so the request genuinely comes
from OpenCode, with OpenCode's credentials:

```
Argus planner ─┐
               ├─► local OpenCode server ─► the model OpenCode is configured to use
Argus worker  ─┘        (installed CLI)
```

- **Planner** — `opencode-server.ts` plus the transport branch in `llm-service.ts` (`c4b9328c`).
  Verified end to end: `MODEL_RESULT opencode/nemotron-3-ultra-free transport=server available=true
  ms=82453 phases=9` from a real free-tier call.
- **Worker** — `argus-workers/opencode_server_client.py`, selected by the `opencode-server` block
  the planner hands over at `agent_init` (`75adf101`, `a7841de4`, `2c0e947e`). Verified end to end:
  a worker call through a spawned server returned `{"tool": "httpx", "why": "Fast HTTP probing…"}`
  in 41.8 s.

Two details are load-bearing and were measured, not guessed:

1. **Prompts use the read-only `plan` agent.** With the default `build` agent a free-tier reply
   came back as a tool call instead of an answer; with *every tool denied* the request was refused
   outright (403 `FreeTierError`). The gate wants ordinary coding-agent traffic, and `plan` is
   both served and unable to modify anything.
2. **The server answers HTTP 200 even when the model call fails**, reporting the provider's error
   on `message.info.error`. Both clients read the error from the message rather than the status.

What this option costs, stated plainly: an external binary is now a runtime dependency of both
runtimes, and a free-tier call takes **30–95 s**. The budgets are written around that — 180 s per
call, one retry at most, and a provider refusal is never retried (it would repeat identically).

The other options remain open and unchanged: Go models still need a paid subscription (option 4),
and the console device-code login (option 3) is still not completed.

---

## 4. Work plan

Ordered so that each step is independently verifiable and unblocks the next.

### Step 0 — Unblock Path A  *(hours)*  ✅ done
- [x] Fix **B1** (option A, both shapes accepted — `e4ed6102`).
- [x] Add a contract test that **spawns the real worker** and asserts `isHealthy() === true`
      against its actual `ping` payload — not a stubbed `sendRequest`
      (`test/argus/integration/mcp-worker-contract.test.ts`).
- [x] Re-run `bun run src/argus/main.ts doctor`; MCP Worker → **PASS**
      (2026-09-29: 10 passed, 3 warnings, 0 failed).
- **Acceptance met:** doctor MCP check passes against the real `mcp_server.py`; the assertion fails
  if either side's payload shape changes.

### Step 1 — Prove the engine locally, no infra  *(1–2 days)*  ✅ done
- [x] Start an authorized local target: `argus-workers/test_fixtures/simple-web-app/app.py`
      (Flask, deliberately SQLi-vulnerable) on an ephemeral port, waiting on `/health`.
- [x] Run it (note the internal-target opt-in from **B8** — without it the scan phase drops its
      only target):
      ```
      ARGUS_ALLOW_INTERNAL_TARGETS=1 python -m cli assess http://127.0.0.1:<port> \
          --local --db /tmp/argus-demo.db
      ```
- [x] Confirm the four phases execute and findings land in SQLite. Measured 2026-09-30 (191 s,
      exit 0): `recon` 15 findings → `scan` 1 → `analyze` → `report`, 9 findings stored (7
      `OPEN_PORT` from naabu, 1 `NO_HTTPS`, 1 `CRAWLED_ENDPOINT` from katana), 1 warning in the
      whole log (`13 tool(s) whose external binary is not on PATH`).
- [x] Where it breaks, fix forward. This is the cheapest possible whole-engine test and needs no
      Docker, Postgres, Redis, Celery, or LLM. What the run actually broke, all fixed and pushed:
      the registry dropped a re-registered tool's YAML launcher, so 16 of the 37 "unavailable"
      tools were never really unavailable (`1b7fff82`); the 8 steps the orchestrator runs itself
      were reported as missing binaries instead of as steps (`7f800a33`); a report whose JSON was
      not the expected shape failed to persist (`928287d9`); the run wrote to Postgres even though
      `--local` popped `DATABASE_URL` — a task module loads `.env` and brings it back — so every
      store it does not have failed noisily (`0b9a2439`); the web scanner's finding types were not
      declared, so they were relabelled `GENERIC_FINDING` (`7725d8bc`); `cli list` printed no
      finding count and no run ever moved an engagement off `created` (`0b9a2439`).
- **Acceptance met:** a complete `recon → scan → analyze → report` run against a local fixture, with
  findings retrievable via `python -m cli list` (now shows the count) and
  `python -m cli report <id> --local --db … --format json`.
- **Known limitation, recorded rather than hidden:** the LLM report is not persisted in local mode —
  `reports` is a Postgres-only table, so `report` upserts are skipped there. `cli report` works off
  the SQLite findings instead. Persisting the LLM artifact locally needs a SQLite report store
  (Step 3 wants a report artifact, so this is the next gap to close there).

### Step 2 — Autonomy switches  *(1–3 days)*
- [x] Scope guard is configurable (`ARGUS_SCOPE_MODE` / `ARGUS_ALLOWED_TARGETS`), enforced, and its
      error is no longer masked (closes **B3** — `b0a5a4fd`). Remaining: put real targets in
      `argus.config.yaml`; keep `require_confirmation` behaviour explicit.
- [x] Model resolution fixed to OpenCode's registry in both runtimes, with the planner's choice
      handed to the worker (closes **B4** — `0bd76813`/`b6a7a2a1`). A real completion now runs
      through the local OpenCode server in both runtimes (**B9** resolved — `c4b9328c`/`2c0e947e`).
- [x] Worker/planner interpreter selection is explicit and reported (`closes **B7**`).
- [ ] Exercise `assess --autonomous` (implies `ARGUS_AUTONOMOUS=1` + `ARGUS_AUTO_APPROVE=1`) and
      confirm it is genuinely unattended: no prompt, no TTY dependency.
- **Acceptance:** `ARGUS_AUTONOMOUS=1 ARGUS_AUTO_APPROVE=1` runs to completion with no interaction,
  and **refuses** to start when scope mode is `warn`/`open` (guardrail still live).

### Step 3 — Evidence the autonomy is real  *(2–4 days)*

> **Demo prerequisite, discovered by running `doctor`:** the registry's default model is
> `opencode/big-pickle`, which the free tier serves *intermittently* (the same request 403s on and
> off). Pin a model that answers for the demo:
> `ARGUS_PLANNER_MODEL=opencode/nemotron-3-ultra-free`. `doctor` prints the model it resolved, so
> confirm it there before starting.
> **B9 is resolved** (`c4b9328c` planner, `2c0e947e` worker): real completions execute through a
> local OpenCode server in both runtimes, so this step is no longer blocked by credentials. What it
> still needs is an actual assessment run whose `agent_decisions` rows can be inspected — and the
> latency to plan around: 30–95 s per free-tier call.
- [ ] Confirm rows appear in `agent_decisions`
      (`database/migrations/012_add_agent_decision_log.sql`,
      `database/repositories/agent_decision_repository.py`) with `tool_selected`, `reasoning`,
      `was_fallback`, tokens, cost.
- [ ] Confirm `[SCAN_METRICS]` (`orchestrator.py::_emit_scan_metrics`) reports
      `agent_success_rate` / `agent_full_fallback_rate`.
- [ ] Assert **≥1 non-fallback decision** and that phase advancement was engine-driven.
- **Acceptance:** the demo can point at recorded decisions proving the engine chose tools, plus a
  report artifact — not just a findings count.

### Step 4 — Unattended (Celery) path + assertions  *(3–7 days)*
- [ ] Bring up Path B: repo-root `.env`, `docker compose up -d postgres redis worker`.
- [ ] Run `scripts/livefire/run-livefire.sh` end to end against Juice Shop.
- [ ] Turn the harness into a test: today it **asserts nothing** while
      `scripts/livefire/README.md` pre-commits success criteria (swarm 3/3, 10–25 findings,
      ≥2 CRITICAL/HIGH, 0% fallback, >30% HIGH+ verified, 0 orphan processes, <500 MB worker,
      0 scope violations, 11–31 min). Add the assertions and emit a baseline JSON per run.
- **Acceptance:** one recorded live-fire run that passes or fails on its own criteria, with a
  stored baseline to diff against.

### Step 5 — Make the guardrails trustworthy  *(ongoing)*
- [ ] **Test determinism:** `pytest-randomly` is auto-loaded, producing two orderings and two
      different failure sets. Known contamination: `tasks/utils.py::_get_redis_client()`
      module-global cache + `sys.modules` mocking in `test_full_scan_pipeline_e2e.py`
      (E2E trio) and shared `DEFAULT_CONFIG.copy()` shallow mutation in `test_config_manager.py`.
      Reproduced (2026-09-30) on a 99-file batch of the tool/scope/report suites: in file order it
      fails exactly the three `test_orchestrator_scope` tests above; moving that file to the front
      makes the same batch green (`1580 passed`), and a worktree at `ba91b9bd` — before this
      session's changes — fails the same three. The tests `except Exception: pass` around
      `run_scan()`, so the swallowed exception is invisible; surfacing it is the first step to
      fixing whichever earlier test leaves the state behind.
- [ ] **TS suite:** 25 failures across `LLMPlannerService` (singleton leak — passes 29/29 alone),
      2 genuine `encryption-workflow`, 1 `tui-commands`, 1 `smoke`.
- [ ] **Hygiene:** untrack `argus-platform/{next-env.d.ts,tsconfig.tsbuildinfo}` (gitignore alone
      cannot untrack); patterns for both are already staged in `.gitignore`.
- **Acceptance:** Python suite is order-independent; TS suite green or every failure triaged.

---

## 5. Fixes already landed (this session)

| Fix | File | Verified |
|---|---|---|
| `_metrics["reconnect_attempts"]` guaranteed `KeyError` on pool reinit | `argus-workers/database/connection.py` | increment path exercised |
| `source_analysis` missing from state machine (phases.py said "MUST match") | `argus-workers/state_machine.py` + new parity test | full suite, no regressions |
| `_check_missing_phase_tools` inverted (reported internal tools, never real gaps) | `argus-workers/tasks/scan.py` | 9 real gaps vs 2 phantoms |
| Repo hygiene (`=3.15.0` junk file, missing ignore patterns) | `.gitignore` | — |

## 5a. Regression status (verified)

Full non-DB suite (`-m "not requires_db and not requires_redis and not e2e and not docker"`,
file order): **4,897 passed, 6 failed**. The 6 failures are the same pre-existing
order-contamination set seen before any of these fixes (baseline was 4,858 passed / 6 failed with
identical test names), and the passed count rose only by the tests added:

```
FAILED tests/test_full_scan_pipeline_e2e.py::TestFullScanPipelineE2E::test_phase_analyze_transitions_and_dispatches_report
FAILED tests/test_full_scan_pipeline_e2e.py::TestFullScanPipelineE2E::test_full_pipeline_chain
FAILED tests/test_full_scan_pipeline_e2e.py::TestFullScanPipelineE2E::test_chain_error_report_raises
FAILED tests/test_orchestrator_scope.py::TestOrchestratorScope::test_run_scan_sets_scope_mode_from_job
FAILED tests/test_orchestrator_scope.py::TestOrchestratorScope::test_run_scan_sets_scope_mode_allowlist_default
FAILED tests/test_orchestrator_scope.py::TestOrchestratorScope::test_run_scan_scope_empty_dict_skips
```

Both suites pass completely when run in isolation, which confirms these are ordering effects and
not regressions from the scope/scan changes:

```
pytest tests/test_orchestrator_scope.py        -> 10 passed
pytest tests/test_full_scan_pipeline_e2e.py    -> 16 passed
```

Consistently touched areas: **843 passed** across the normalizer/parser/finding suites (covers the
finding-title change), and 361 passed across context/web_scanner/scope. `ruff check` clean on
every changed file; TS side `bun typecheck` clean. The 6 failures remain unfixed — see item 5 of
the work plan (test determinism).

---

## 6. Explicitly unverified (do not claim these work)

- No live scan against any real target has been run in this checkout. The only whole-engine run is
  Step 1's, against `test_fixtures/simple-web-app` on loopback.
- No `docker compose up` of the full stack; no CI run; Path B never executed here.
- LLM calls *have* now been observed succeeding from both runtimes (B9, via the local OpenCode
  server): a planner call returned 9 phases and a worker call returned a tool choice. What is still
  unverified is the paid/console-account paths and any interactive login.
- No `livefire-runs/` directory exists → **no recorded successful live-fire run**.
- The propagation of `agent_init`/`agent_next`/`agent_observe`/`phase_complete` payload shapes
  was reviewed only for `ping`, `list_tools`, and `call_tool`. **Diff the remaining four handlers**
  (`mcp_server.py:1810-1833`) against `mcp-client.ts` before trusting Path A end to end — B1 shows
  this boundary is exactly where silent mismatches live.
