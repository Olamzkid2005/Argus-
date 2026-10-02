# Argus: Trustworthy Terminal-First Demo Implementation Plan

**Date:** 2026-09-30  
**Status:** Proposed implementation plan; no items below are complete merely because related code exists.  
**Basis:** Source audit and targeted mocked reproductions, not historical documentation scores.  
**User-selected scope:** A trustworthy web/API demo, launched by typing `argus` in a terminal, with an OpenCode-like interactive experience.

This plan supersedes earlier demo-readiness percentages and acceptance claims for the next demo. Historical logs remain useful evidence of individual behaviors, not proof of the stricter bar below.

## 1. The demo we are building

The operator types `argus`, sees the existing Argus terminal UI, selects a model, reviews an explicit authorized target and limits, and starts an assessment with `/assess <target>`. After one up-front authorization, Argus discovers the application, authenticates with supplied lab identities, chooses and adapts tests from observations, proves a vulnerability, and saves findings, evidence, and a report without per-tool coaching.

The operator can inspect decisions and evidence, cancel safely, reopen the engagement, and resume eligible interrupted work. Failure and partial coverage remain visible; they never become a green success banner.

**Honest demo claim:** “A bounded, target-scoped autonomous web/API assessment with authenticated testing and independently reproduced findings.”

**Not the claim:** “Fully autonomous red team,” autonomous MFA bypass, arbitrary exploit execution, proven multi-host pivoting, or comprehensive vulnerability coverage.

### Two distinct release gates

- **Gate A — primary product demo:** real `argus` launcher → full-screen TUI → WorkflowRunner → real TypeScript bridge → real Python MCP worker → authorized lab → evidence/report.
- **Gate B — specialist validation:** separate Celery/live-fire run proving IDOR, Auth, and API specialist activation, actual execution, and terminal outcomes.

Passing Gate B does not prove the TUI invokes the swarm. Connecting Celery swarm execution to the TUI is a follow-on feature unless explicitly added to scope.

### Final acceptance matrix

| Requirement | Required evidence |
|---|---|
| Bare `argus` works | Real pseudo-terminal launch, responsive home/prompt, clean exit; correct config from the caller's directory |
| One launch path | `/assess` reaches the intended runner exactly once; CLI and TUI share assessment policy |
| Discovery is real | Request log plus persisted recon shows a login surface, at least two API endpoints, and a parameter/object-bearing resource discovered from links/forms/API descriptions |
| Authentication is real | Two supplied lab users have distinct authenticated sessions and a verified identity endpoint; invalid credentials fail |
| Autonomy is real | At least one successful LLM-chosen action and one subsequent observation-driven change of endpoint, arguments, or capability; each matches the actual execution log |
| Impact is real | At least one authenticated cross-user object-access finding with ownership proof and controls; not merely an HTTP success code |
| False proof is prevented | Patched object endpoint, public page, clean SQL responses, inert XSS text, failed reproduction, 403 chain step, and 404 JWT endpoint do not become verified/confirmed exploits |
| Scope holds | Requests to an out-of-scope sentinel are blocked and its request counter stays zero, including redirect and browser-subresource tests |
| Recovery is real | Worker interruption and controlled stop preserve the engagement; restart does not reset budget or silently repeat completed actions |
| Results survive exit | Findings, decision/execution audit, evidence hashes, and report remain readable after restarting `argus` |
| Swarm is real | Gate B records IDOR/Auth/API activation, an authorized target, at least one actual tool execution per specialist, and successful completion; errors/timeouts fail the gate |
| Repeatability | Three fresh Gate A runs and three fresh Gate B runs pass; no cached findings or prerecorded LLM decisions substitute for live operation |

All required gates are pass/fail. Finding counts, log-line counts, and “non-fallback decision” counts alone cannot pass them.

## 2. Implementation decisions

1. Reuse the existing full-screen OpenTUI/Solid interface and routes; do not start a UI redesign.
2. Use the TypeScript WorkflowRunner/MCP path as the main product path. Repair shared Python contracts for the worker/swarm gate too.
3. Keep SQLite as the primary engagement store. Persist the primary demo's decision/execution audit locally; PostgreSQL must not be required merely to record a TUI decision.
4. Retain the existing Redis-backed autonomous lock requirement until a separately tested alternative is approved. Gate B additionally requires a disposable PostgreSQL database and Celery worker.
5. Use the existing provider/model selection mechanism, with the selected model handed to planning and worker calls. Do not silently change providers or consume ambient credentials.
6. Introduce an explicit, bounded web/API demo profile/workflow. Exclude repo SAST/SCA, cloud enumeration, generic generated scripts, and unsupported red-team capabilities instead of falsely completing them.
7. No automatic widening of scope, implicit unscoped mode, host-network shortcuts, or host fallback for generated code.
8. Initial scope/auth/limits approval is explicit. Only the approved low-impact tests run unattended afterward; any request for expanded permission stops or pauses.
9. Keep historical confidence scores separate from proof status. Only a proof-bearing independent verifier can mark an exploit reproduced/confirmed.
10. Reuse existing fixtures where useful, but improve discovery and add secure controls. Never expose fixture manifests, expected exploit answers, or synthetic secrets to the planner.

### Initial demo limits to tune before freezing

Proposed starting configuration: one authorized origin, no general port-range scan, 20-minute wall-clock limit, 24 tool executions, 8 LLM calls, 2 target HTTP requests/second, and bounded concurrency. Tool and verification timeouts must fit the remaining engagement deadline.

These are proposed limits, not existing guarantees. Count actual HTTP traffic, not only tool launches. Configure token/cost ceilings from the selected model's real accounting; unknown cost is explicitly unknown, never silently `$0`. Reserve conservative usage before a call, reconcile afterward, and do not start calls that exceed the configured remaining allowance. Tune once on the disposable lab, then freeze the rehearsal profile.

## 3. Execution order and small work packages

Each numbered package is one focused change. Split it further if implementation exceeds roughly five directly related files. Add regression tests before each fix, run relevant tests/typecheck, review the diff, and checkpoint the result before advancing. Checkboxes are implementation evidence, not planning progress.

### Stage 1 — The real `argus` experience

#### Implementation task queue

Work in this order; each task has its own acceptance evidence. Completing launcher work does not complete Stage 1 or authorize a scan.

**Progress (2026-10-01):** tasks 1–3 have passing automated evidence; task 4 is implemented but its automated PTY gate is slow/flaky (manual terminal proof only); tasks 5–7 not started; task 8 checkpoint open. Launcher completion is not Stage 1 completion and does not authorize a scan.

1. **Launcher routing:** add a regression showing bare `argus` selects the full-screen default TUI, not `run --interactive`; preserve caller cwd, Argus mode, and TUI options such as `--model`. **Done — see 1.1 evidence.**
2. **Foreground lifecycle:** test and implement signal forwarding, failed spawn/nonzero child status propagation, and listener cleanup at both launcher layers. Keep CLI help and existing assessment/report/resume/doctor commands on their current command path. **Done — see 1.1 evidence.**
3. **Workspace/assets:** prove worker/workflow paths resolve from the installation while scope/config resolves from the caller's workspace; explicitly load the Solid terminal preload without relying on package-directory `bunfig.toml`. **Done — see 1.1 evidence.**
4. **Terminal smoke gate:** launch the real binary in an isolated pseudo-terminal from the repository root and another workspace; verify the Argus prompt responds and exits cleanly. Do not invoke assessments or provider calls. **Implemented, but the automated PTY pass is slow/flaky and not yet a reliable pass; manual terminal proof only — see 1.1 evidence.**
5. **One assessment service:** replace duplicated slash/natural-language launch branches with one policy/service boundary; preserve model, credential references, cache mode, engagement identity, and limits. Tests assert exactly one runner invocation.
6. **Typed UI progress:** send structured events to the scan store/dashboard, never scanner output to `session.prompt`; test that assessment traffic cannot invoke the coding agent.
7. **Truthful results and stop:** render failed/partial outcomes as such, preserve persisted state, and wire graceful stop. Tests cover success, failure, partial result, duplicate submission, and cancellation using a controlled runner.
8. **Stage 1 checkpoint:** run relevant handler/launcher tests and package typecheck; verify `/doctor` in an explicitly approved isolated worker environment. Keep the checkpoint open until all evidence is recorded. **Open:** launcher tests and package typecheck pass, but `/doctor` in an isolated worker environment is not yet verified.

#### 1.1 Make bare `argus` enter the assessment-capable TUI

**Source issue:** `bin/argus` points to `src/argus/index.ts`, whose no-argument branch starts `src/index.ts run --interactive` and changes cwd to the package. The full-screen TUI's `$0 [project]` route and assessment prompt interception are separate.

- [x] Route bare `argus` through the existing full-screen TUI default command in Argus mode, preserving the operator's working directory and arguments.
- [x] Resolve worker/workflow assets independently of cwd; load scope/config from the intended workspace. Keep `argus doctor`, `assess`, `report`, and `resume` subcommands functional.
- [x] Forward signals, propagate failures, and restore the terminal on exit. Missing dependencies produce actionable errors, not a blank or hanging UI.

**Evidence (2026-10-01).** `src/argus/launcher.ts` (`launchTui`, `spawnForeground`) now owns the launch path: `bin/argus` and `src/argus/index.ts` both re-exec through it; bare and option-first invocations go to the full-screen TUI with `ARGUS_MODE=1` and an `OPENCODE_ROUTE={"type":"home"}` default; `cwd` stays the caller's workspace; the Solid preload resolves as an absolute URL instead of via the package `bunfig.toml`. In `app.tsx` the Argus dashboard no longer overrides the home route, and in `logo.tsx` an orphan text node that aborted the first render was removed.

Evidence commands and results (from `Argus-Tui/packages/opencode/`):

- `bun test ./test/argus/unit/launcher.test.ts ./test/cli/tui/thread.test.ts` — 6 pass / 0 fail. Proves routing, preserved cwd, `--model` forwarding, absolute preload/assets from a separate tmp workspace, failed-spawn cleanup, and nonzero-status propagation.
- `bun test ./test/cli/tui/app-lifecycle.test.ts` — 11 pass / 0 fail. Proves the Argus home mounts the `/assess` prompt with no render error and that `SIGTERM`/`SIGHUP` destroy the renderer and remove their listeners.
- `bun run typecheck` — passes.
- `argus --help` prints the ARGUS banner and the full command list, so `doctor`/`assess`/`report`/`resume` stay on the yargs path.

**Operator terminal proof.** With `~/.bun/bin/argus` symlinked to `Argus-Tui/packages/opencode/bin/argus` (user-approved, user-level only — no package install and no shell-profile change), typing bare `argus` from `$HOME` opened the branded home TUI: ARGUS logo, “Operational”, Quick Actions including `/assess <target>`, all-green System Status, and the “Ask anything…” prompt.

**Not yet evidenced.** The automated real-PTY gate (`test/argus/e2e/launcher.test.ts`) is slow/flaky on a loaded machine — cold start measured at ~24s idle and past 180s under load, and Bun's PTY never answers terminal capability queries — so it is not currently a reliable pass; the deterministic prompt assertion lives in the in-process `app-lifecycle` test. `/doctor` in an isolated worker environment is unverified, and Stage 1.2 is untouched. **Checkpoint 1 therefore stays open.**

**Likely files:** `Argus-Tui/packages/opencode/bin/argus`, `src/argus/index.ts`, `src/index.ts`, `src/cli/cmd/tui/thread.ts`; launcher tests.

**Verification:** stub-spawn argument/cwd tests plus a real pseudo-terminal launch from the repository root and a different authorized workspace. No assessment or target requests during startup testing.

#### 1.2 Use one TUI assessment handler

- [ ] Route slash commands and recognized natural-language requests through the same assessment service/policy; preserve the selected model, credentials, cache mode, engagement ID, and limits.
- [ ] Render typed progress directly in the scan UI. Do not call `session.prompt` to feed scanner logs back into a general coding agent as user instructions.
- [ ] Check `result.success` and partial/failed state before displaying completion; do not launch duplicate engagements or print raw report text into the terminal renderer.

**Likely files:** `src/cli/cmd/tui/component/prompt/index.tsx`, `src/argus/tui-commands.ts`, `src/argus/commands/assess.ts`, `src/argus/tui/scan-store.ts`; command tests.

**Verification:** component/handler tests for exactly-one launch, model handoff, structured progress, failed result, and graceful stop. TUI launch proves routing only, not autonomous pentesting.

**Checkpoint 1:** `argus` opens the correct interface, `/doctor` works, and a stubbed assessment cannot falsely display success. Do not run live scans yet.

### Stage 2 — Correct execution across the boundary

#### 2.1 Repair Python tool dispatch

- [ ] Keep execution timeout separate from tool-schema arguments; invalid parameters fail once rather than retrying because the error contains `timeout`.
- [ ] Build CLI arguments from the canonical tool definitions, preserving supported named parameters and required flags instead of forwarding only a bare target.
- [ ] Register login/register through the normal factory and use the auth-aware wrapper consistently.

**Likely files:** `argus-workers/agent/react_agent.py`, `agent/tool_registry.py`, existing canonical argument builder; `tests/test_react_agent.py` and factory/contract tests.

**Verification:** the actual phase factory reaches a fake runner once with correct arjun parameters; schema errors do not retry; login/register are available. No external scanners required.

#### 2.2 Freeze the next/observe/action protocol

- [ ] Define one advancement owner: `agent_next` returns the next action; `agent_observe` records the result and acknowledges it without consuming another action. Update both implementations and tests together.
- [ ] Carry action ID, tool arguments, reasoning, and chooser provenance through MCP to execution; validate arguments before dispatch.
- [ ] Send top-level engagement identity, worker execution timeout, and the explicit run policy through tool RPC. The transport timeout must allow cleanup, not merely abandon a running tool.

**Likely files:** `mcp_server.py`, `agent/session_store.py`, `src/argus/bridge/mcp-client.ts`, bridge types, `src/argus/planner/executor.ts`; protocol tests.

**Verification:** three planned actions execute exactly once in order; observe does not skip the middle action; selected arguments reach the runner unchanged except documented normalization; unknown actions are rejected.

#### 2.3 Make outcome and coverage accounting honest

- [ ] Distinguish selected, started, succeeded-empty, succeeded-with-findings, failed, blocked, skipped, and timed-out actions.
- [ ] Count only successfully performed capabilities as covered. Unsupported required capabilities produce a gap/partial or failed result, not a clean completion.
- [ ] Ensure SAST/SCA cannot report success when a runner is absent or failed, and local CLI analysis/report failures propagate to a failed/nonzero result; these are regression guardrails, not an expansion of the demo profile.
- [ ] Apply the declared recovery policy using stable phase identity; keep deterministic fallback visibly labeled and bounded.

**Verification:** zero executed tools is not agent success; missing required tool fails readiness; failed/skipped work is eligible for bounded replanning; raw stdout is never a vulnerability. Regression tests cover absent/failed SAST runners and local CLI phase failures so neither path can exit as successful completion.

**Likely files:** `src/argus/planner/{planner,executor}.ts`, `src/argus/workflow-runner.ts`, Python scan metrics and local CLI; execution tests.

**Checkpoint 2:** real TypeScript bridge → production `mcp_server.py` contract tests pass with controlled safe tool stubs. A substitute test server alone is insufficient.

### Stage 3 — Authorization before any live execution

#### 3.1 Isolate run scope and remove implicit permission

- [ ] Carry engagement-scoped authorization explicitly; replace the unkeyed process-global fallback where concurrent callers can inherit another run's scope.
- [ ] Remove automatic `ARGUS_ALLOW_UNSCOPED` enabling. Resume uses the same validation as initial execution.
- [ ] Permit local/private targets only with explicit internal-target opt-in plus authorization; keep direct cloud-metadata access blocked. Apply the policy to agents, safety nets, and every specialist target/peer/fallback path.

**Likely files:** `tools/scope_validator.py`, `feature_flags.py`, `agent/{react_agent,swarm}.py`, orchestrator scope handoff; scope tests.

**Verification:** concurrent A/B engagements cannot borrow scope; opt-in alone is insufficient; allowed origin works; wrong origin/port and metadata are rejected.

#### 3.2 Enforce scope at requests and subprocess targets

- [ ] Parse and validate every target argument, discovered URL, and redirect hop; remove substring-based authorization. Keep URL-origin permission distinct from broad host/port permission.
- [ ] Guard Playwright navigations, requests, subresources, and authenticated requests. Out-of-scope navigation must not receive session headers/cookies.
- [ ] Bound external tools through a demonstrable egress policy where request-level control is unavailable; exclude tools whose traffic cannot meet the demo policy. Log approved model/Redis/worker infrastructure destinations separately from target scope.

**Likely files:** `tools/tool_runner.py`, MCP scope handling, `src/argus/shared/target-validator.ts`, `src/argus/browser/engine.ts`, executor wiring; boundary tests.

**Verification:** an out-of-scope local sentinel sees zero requests from direct tools, redirects, browser subresources, and crafted tool arguments. Target-controlled text cannot alter authorization.

**Checkpoint 3:** safety suite passes. Generated scripts, speculative post-exploitation, and broad cloud/network phases remain disabled. Live lab execution requires separate explicit permission and disposable infrastructure.

### Stage 4 — Findings that mean what they say

#### 4.1 Introduce strict proof status

- [ ] Use a consistent proof result: suspected, reproduced, not reproduced, inconclusive, or unsupported, with evidence/control references and verifier error details.
- [ ] Remove metadata/error-artifact confidence promotion to verified/confirmed; failed verification cannot be overridden by repeated promotion calls.
- [ ] Disable or explicitly mark placeholder reproduction/chain verification unsupported until implemented. HTTP reachability and process exit zero never constitute exploit proof.

**Likely files:** `tools/verification/{confidence_scorer,finding_promoter}.py`, verification result integration, `src/argus/engagement/confidence.ts`, shared finding types; proof tests.

**Verification:** all audit false-proof examples become regressions: identical SQL pages, descriptor/error artifacts, empty evidence packages, 403 chain response, 404 JWT response, ordinary SSRF page, and failed verification.

#### 4.2 Prove authenticated object access, not just a status code

- [ ] Accept two actual credentials/identities and a structured discovered resource endpoint; never fabricate the second username.
- [ ] Establish resource ownership, valid login, and unauthenticated/invalid-credential controls before testing cross-user access.
- [ ] Confirm only when user B receives user A's unique resource data that policy should deny; secure twin endpoint returns denial and is not confirmed.

**Likely files:** `browser/verifiers/bola.ts`, `workflow-runner.ts`, browser auth helpers, credential role handling; verifier tests.

**Verification:** vulnerable and secure twin fixtures, public-resource control, failed login, denied same-URL response, and unrelated 200 response. Use synthetic lab records, never real sensitive data.

#### 4.3 Make one browser-execution verifier trustworthy

- [ ] Verify XSS with a unique execution nonce observed in the intended browser context, installed before navigation; ordinary script tags or reflected text are insufficient.
- [ ] Use the discovered endpoint/parameter and appropriate separate session for victim-view testing, not a guessed `/contact` page.
- [ ] Preserve request, response, execution event, and cleanup outcome; unrelated scripts and encoded/inert payloads do not pass.

**Likely files:** `browser/verifiers/xss.ts`, browser evidence hooks, workflow verifier routing; XSS verifier tests.

**Verification:** actual Playwright vulnerable/escaped/CSP-blocked controls. XSS is supplementary breadth; the mandatory presentation exploit is the authenticated object-access proof.

**Checkpoint 4:** targeted proof tests pass before real-model rehearsal. Retain SQLi/SSRF/JWT checks as suspected or unsupported unless they independently satisfy equivalent controls; disable their weak automatic confirmation paths.

### Stage 5 — A genuinely adaptive authenticated assessment

#### 5.1 Persist observations and select after execution

- [ ] Convert recon/tool results into structured endpoint, parameter, auth, finding, and failure observations keyed by engagement; include them in the next decision.
- [ ] Request one actionable choice at a time after observing prior execution. Carry its arguments to the executor, rather than preordering a complete tool list and discarding arguments.
- [ ] Allow bounded revisits when new arguments/identity/evidence justify them; deduplicate by action signature, not only tool name. Honor stop decisions and required coverage policy explicitly.

**Likely files:** `mcp_server.py`, `agent/session_store.py`, `agent/react_agent.py`, executor/bridge observation contract; planning tests.

**Verification:** with a deterministic fake model, action 2 must depend on action 1's newly discovered endpoint; unsupported/invented endpoint and scope-expansion decisions are refused. With a real model, require a successful execution plus an observation-driven change; selection logs alone cannot pass.

#### 5.2 Carry real authentication through the selected tool path

- [ ] Store identity-scoped sessions once established and inject the correct cookies/headers into supported tools and verifiers; never mix users.
- [ ] Detect expiration using a verified protected identity/resource check; perform one bounded refresh or pause with a clear auth error.
- [ ] Keep credentials/tokens out of prompts, stdout, report, decision args, and shared caches; store secret references and protected auth checkpoints where needed.

**Likely files:** existing auth manager/context/checkpoints, tool adapters, TUI credential options, verifier/session handoff; auth integration tests.

**Verification:** cookie propagation reaches a protected endpoint; users remain distinct; invalid and expired sessions are not treated as successful access. SSO/MFA requiring operator input is unsupported/paused, not autonomously bypassed.

**Checkpoint 5:** one controlled end-to-end fixture path discovers → logs in → chooses/adapts → proves object access → persists evidence. Model output and expected findings may be controlled for this checkpoint, but it is not the final live-model demo.

### Stage 6 — Bounded operation and restart safety

#### 6.1 Enforce one cumulative budget

- [ ] Persist wall-clock deadline, LLM calls/tokens/actual cost or explicit unknown-cost accounting, tool count, and request usage per engagement. Include failed/malformed/fallback calls.
- [ ] Bound in-flight model/tool/request calls to remaining time; no deterministic remainder after an authorization, cancellation, or hard budget stop.
- [ ] Cancel only engagement-owned process groups/requests and report timeout/cleanup errors. Prevent unbounded subprocess output buffering on the allowed demo tools.

**Likely files:** LLM service/action accounting, active run controller, bridge supervisor, tool runner, engagement storage; budget/cancel tests.

**Verification:** priced fake response reaches the persisted ledger; a slow call cannot outlive the engagement deadline indefinitely; cancellation terminates owned children while another engagement remains running.

#### 6.2 Resume the saved run, not a newly invented assessment

- [ ] Persist the approved plan/policy, workflow version, action signatures/results, observations, secret references, proof status, and budget usage in primary storage. Store explicit UTC created/started/completed/checkpoint timestamps for the engagement and actions; do not infer missing timestamps as successful progress.
- [ ] Restore scope/auth/model/limits and reconcile in-flight actions on resume. Retry read-only actions safely; do not automatically replay state-changing work after ambiguous interruption.
- [ ] Validate checkpoint timestamp/order and workflow compatibility before resuming; preserve original timestamps and cumulative usage rather than resetting either.
- [ ] Use explicit paused/interrupted/partial/failed/completed states. Verify checkpoint deserialization and report persistence; no false success when analysis or storage fails.

**Likely files:** `src/argus/commands/resume.ts`, engagement store/recovery, workflow runner, decision checkpoint integration; restart tests.

**Verification:** terminate the actual worker mid-run, reopen `argus`, resume eligible work, retain usage and prior results, and finish without duplicated successful actions. Checkpoint/action timestamps remain present and ordered across restart. Reject incompatible workflow or wider scope.

**Checkpoint 6:** normal finish, provider failure, expired auth, interruption, deadline, and cancellation all produce truthful terminal states and leave no engagement-owned scanners behind.

### Stage 7 — Discoverable lab and the requested swarm proof

#### 7.1 Build a small, resettable discovery/verification lab

- [ ] Extend the existing auth fixture with a linked landing page/login form, two API links or an API description, identity checks, and user-owned resources; add a vulnerable ownership check and a secure twin.
- [ ] Supply two synthetic users and unique per-run markers. Keep the answer manifest in the harness only. Provide test-only reset and target-side request logging.
- [ ] Include independent negative controls and an out-of-scope sentinel; integrate the existing XSS fixture where useful without requiring its source to be read by the planner.

**Likely files:** `argus-workers/test_fixtures/auth-bypass/app.py`, fixture tests/manifests, existing XSS fixture; lab harness.

**Verification:** fixture contract tests prove ownership/denial/login behavior and that links/forms actually expose the required signals. The current auth fixture is insufficient as-is: its resources are largely publicly accessible and it lacks a discoverable home/login page.

#### 7.2 Add explicit swarm harness opt-in

- [ ] Add validated harness options for aggressiveness/scan mode/required specialists. Keep moderate defaults; elevated scanning must be explicit. Proposed controls: `AGGRESSIVENESS=high`, `SCAN_MODE=swarm`, `REQUIRE_SWARM=1`.
- [ ] Save the exact effective job payload, scope, feature configuration, engagement/run IDs, and per-specialist structured events. Use fresh engagements; do not delete/reuse another run's findings.
- [ ] Assert each required specialist activates, receives an authorized target, starts actual tool execution, and completes successfully. No-activation, errors, timeouts, missing events, or fake chooser provenance fail.

**Likely files:** `scripts/livefire/run-livefire.sh`, `assert-livefire.py`, README, worker swarm events/metrics, harness tests.

**Verification:** malformed opts fail before dispatch; default moderate does not require swarm; “Swarm: no specialists activated” cannot pass; terminal completion with errors is not successful completion. A payload produced by the script—not the unused sample JSON—is asserted.

#### 7.3 Run the actual specialists against discovered signals

- [ ] Apply Stage 3 local scope policy to all specialist targets, peer discoveries, and raw-endpoint fallbacks; remove bypassing re-additions.
- [ ] First prove routing/activation with stubs, then run real IDOR/Auth/API specialist bodies on the resettable lab using actual recon-produced signals.
- [ ] Record per-specialist selected/attempted/executed tools and proof status. Hardcoded suites are labeled deterministic, not LLM-selected.

**Likely files:** `agent/swarm.py`, `tests/test_swarm_wiring.py`, harness verdicts/fixtures.

**Verification:** Gate B requires all three specialists, each with actual successful tool execution and completion; secure controls remain unconfirmed; no unauthorized traffic or owned orphan processes. An assertion cannot be relaxed merely because the run fails.

**Checkpoint 7:** Gate B passes on the discoverable controlled lab. Then perform a supplemental authorized run against the pinned Juice Shop target already present in Compose; do not use arbitrary finding-count ranges as proof or require MFA flows it cannot support.

### Stage 8 — Product presentation and repeatable release

#### 8.1 Make the UI/report reflect the proof ledger

- [ ] Show action reason/provenance, actual execution status, auth identity label, budget, proof status, and coverage gaps; do not display secrets or fabricated success rates.
- [ ] Save a report from the same persisted findings/proof ledger, including reproducible controls and evidence links. Failed storage/report generation is visible and fails the demo gate.
- [ ] Verify evidence/report redaction and file permissions; where encryption is requested, missing keys fail closed or pause instead of silently writing plaintext.

**Likely files:** existing TUI scan/finding/report routes, scan store, report generator, evidence collector; report/UI tests.

**Verification:** TUI, persisted store, report, and harness agree after restart; hashes reference real artifacts; credential/secret canaries do not appear in exported artifacts.

#### 8.2 Freeze one reproducible demo environment

- [ ] Pin interpreter/tool/browser versions and provide an explicit readiness check for the demo subset; verify correct command flags and target types with small fixture probes, not just `--help`.
- [ ] Verify a disposable PostgreSQL schema under one role for Gate B; migration failures are fatal and not silently counted as applied. Validate Redis auth and worker queues/config.
- [ ] Test the chosen delivery method from a fresh workspace. Make `argus` discoverable on PATH using an approved local installation/link; do not rely on an undocumented shell alias. No global installation or shell-profile change without permission.

**Likely files:** existing doctor/startup checks, migration runner/tests, Compose/Dockerfile if used, launcher/install instructions.

**Verification:** fresh environment reaches readiness without manual SQL patching or editing secrets into tracked files. If Docker is chosen, also fix non-root binary locations, worker config and browser installation, and add worker-context build exclusions. A source-checkout demo need not become a cross-platform distributable in this stage.

#### 8.3 Rehearse the exact product and failure paths

- [ ] Run Gate A three times from bare `argus` through `/assess`, with fresh lab state, real worker, and real selected model; run Gate B three times separately.
- [ ] Capture one failure-mode rehearsal each for invalid scope, invalid credentials, provider unavailability, worker interruption/resume, and user cancellation.
- [ ] Run the relevant full test suites in isolated configurations and repeat critical suites in different collection orders; critical acceptance tests cannot skip for absent dependencies. Publish unresolved unrelated failures explicitly.

**Verification:** release requires every final matrix row above. A timeout/missing dependency is a failed gate, not a skipped benchmark. Keep required acceptance tests distinct from optional external integrations.

**Checkpoint 8 — demo ready:** three cold primary runs and three cold swarm runs pass; negative controls never become confirmed findings; recovery and safety evidence is attached. Only then describe the scoped feature as a working demo.

## 4. Test strategy

1. **Contract/unit regressions:** reproduce the audit failures before fixes; assert correct behavior, not the old assumptions.
2. **Real process boundary:** use the actual TypeScript bridge and production Python server with isolated config and harmless controlled runners. Do not substitute only the lightweight test server.
3. **Fixture/browser integration:** run the real HTTP auth and Playwright verifiers against vulnerable and secure twins. Assert request ownership and control behavior.
4. **Controlled model integration:** deterministic fake model proves observation/argument dependencies and safety without provider variability.
5. **Live-model acceptance:** real model must react to runtime discoveries; fixtures, tools, auth, proof, and storage are not mocked. No canned findings/replayed decisions.
6. **PTY/TUI acceptance:** launch the actual `argus` binary and interact with the assessment-capable prompt/dashboard, including reopen and exit.
7. **Failure/security acceptance:** request sentinel, target-controlled prompt injection, timeouts, budget, cancellation, interleaved engagement scopes, invalid auth, and storage failure.

Routine commands (from the indicated directory; exact test lists evolve with each package):

```bash
# argus-workers/ — safe targeted tests; isolate config/secrets and network in fixtures
HOME=/tmp/argus-test-home ./venv/bin/python -m pytest -p no:randomly <changed-test-files>
./venv/bin/python -m ruff check --no-cache <changed-python-files>

# Argus-Tui/packages/opencode/
bun run typecheck
bun test <changed-test-files> --timeout 30000
```

Run service/browser/fixture/live-fire tests only with explicit authorization for their disposable environment. Do not run the existing live-fire reset against shared engagements or the production database.

## 5. The final presentation runbook

This is the intended experience after implementation, not a command sequence to execute now.

1. Prepare the pinned lab, out-of-scope sentinel, isolated storage, permitted model, and required infrastructure. Save tool/config versions; keep credentials outside the repository.
2. Type **`argus`** from the prepared workspace. Show the actual home/prompt and readiness; no package-directory command or hidden alias.
3. Run `/doctor`; confirm model, Python worker, scope, required tools, browser, storage, and lock readiness. Optional missing tools remain clearly separate.
4. Review target origin, supplied identity labels, authorization, exclusions, low-impact test policy, and limits. Approve once.
5. Enter `/assess <authorized-lab-url>`. Do not supply vulnerable endpoints or desired exploit answers. After authorization, do not coach individual tool choices.
6. Watch discovered login/API signals, verified authentication, a successful LLM-selected action, and an observation-driven follow-up. Show execution records, not only reasoning text.
7. Open the reproduced object-access finding: compare owner/other-user/unauthenticated and secure-control evidence. Show that the public/secure controls were not confirmed.
8. Open the saved report; exit and reopen `argus` to demonstrate durable findings and evidence.
9. Show the separate Gate B verdict with per-specialist activation/execution/completion. Label it worker/swarm validation, not TUI swarm execution.
10. Use a second controlled run to demonstrate cancel or worker interruption/resume without losing authorization or budget.

### Evidence bundle per run

Save a unique run/engagement ID, revision, exact approved config/profile with secrets redacted, tool versions, actual model/provider, discovery snapshot, decision/action/execution/observation records, identity labels, proof/control references, target/sentinel request counts, budget ledger, terminal state, cleanup results, evidence hashes, report path, and machine-readable verdict.

Baseline comparisons detect regressions; they do not replace correctness assertions or validate bad initial findings.

## 6. Milestones, dependencies, and scope control

| Milestone | Packages | What is now demonstrable |
|---|---|---|
| M1: terminal entry | 1.1–1.2 | `argus` opens the right interface and reaches one runner |
| M2: safe truthful core | 2.1–3.2, 4.1 | Actual actions/arguments, honest coverage, authorization, no false confirmation shortcuts |
| M3: trustworthy assessment | 4.2–5.2, 7.1 | Discovery → real identities → adaptive test → independent exploit proof |
| M4: unattended resilience | 6.1–6.2 | Budgeted execution, cancel, durable restart/resume |
| M5: specialist proof | 7.2–7.3 | All required specialists run and complete on discovered signals |
| M6: working demo | 8.1–8.3 | Exact TUI experience, reports, fresh-environment readiness, repeated passing acceptance |

Start with 1.1/1.2 for the requested visible entry experience, then fix contracts before live target execution. Package 7.1 can be built alongside scope/proof tests; verifier work can proceed in parallel once the proof/observation contract is frozen. Budget/resume integration depends on stable action identity. Live swarm runs depend on repaired Python execution, scope, authentication, and a validated lab.

This is multiple engineering milestones, not a one-day harness patch. Estimate calendar time after M2: launcher integration, real browser/auth behavior, and cross-process state are the largest current unknowns. Do not promise a date based on historical percentage scores.

### Explicitly deferred

- AD/Kerberos, C2, remote foothold sessions, tunnel-backed pivots, enterprise lateral movement.
- Two-step causal attack-chain execution and impact proof; generated chain scripts stay disabled.
- Autonomous credential acquisition, phishing, SSO/MFA challenge solving, or destructive actions.
- Repository SAST/SCA and broad cloud/network phases in the demo profile; their implementation gaps remain documented, not “fixed” by exclusion.
- Full parity of the Python local CLI; prevent false success if touched, but do not use it as a shortcut around the primary TUI gates.
- TUI-to-Celery swarm integration and broad cross-platform packaging.

### Go/no-go rule

If a required task does not execute, proof is inconclusive, a secure control is confirmed vulnerable, scope leaks, state cannot be restored, or an artifact cannot be saved, the verdict is **not demo-ready**. Report the actual blocker and fix it; do not loosen the test or relabel deterministic scanning as autonomous proof.
