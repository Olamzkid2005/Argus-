# Argus Current Remaining Gaps

> **Status:** Current gap register
>
> **Verified:** 2026-09-01 (after the collection-order and migration-test fixes)
>
> **Purpose:** Record the work that remains before Argus can honestly be described as fully autonomous, production-grade AI red-team pentesting software.
>
> **Evidence policy:** This document is based on current source, configuration, and test evidence. Existing plans and historical completion reports are not treated as proof. A component existing in the repository does not by itself prove that the complete end-to-end behavior works.

## Critical blockers

### 1. Full test suite is not clean

The prior full Python worker-suite run reported:

- 4,908 passed
- 55 skipped
- 7 xfailed
- 27 xpassed
- 4 unexpected failures

The formerly reported DB-context failure and three E2E failures now pass in targeted regression runs. A full-suite rerun is still required before this item can be marked closed.

Three failures were collection-order contamination in the full-scan E2E tests:

```text
AttributeError: 'function' object has no attribute 'run'
```

Affected tests:

- `test_phase_analyze_transitions_and_dispatches_report`
- `test_chain_error_report_raises`
- `test_full_pipeline_chain`

The E2E failures were caused by cached `tasks.analyze` state after mocked imports. Targeted cleanup now makes the affected regression set deterministic; the migration batch test also now clears cached rollout configuration.

The fourth previously reported failure was:

- `tests/test_db_connection.py::test_tenant_context_failure_logs_warning`

It passed in isolation, indicating shared singleton or collection-order contamination rather than a stable isolated defect.

### 2. Autonomous execution is not fully proven

Argus has agent, planner, MCP, and replan components, but code existence is not equivalent to end-to-end autonomy.

Still requiring proof:

- automatic signal-driven deep-scan dispatch,
- automatic post-exploitation dispatch,
- automatic auth-focused scanning after recon detects login/auth endpoints,
- deterministic fallback replanning,
- attack-graph-to-execution feedback,
- behavior when the LLM is unavailable or returns malformed tool calls,
- stopping and recovery behavior after repeated tool failures.

Some execution paths still degrade to deterministic execution or stop rather than autonomously recover and continue.

**Re-run evidence (2026-09-30, unattended `--autonomous` against the local Flask fixture).** A fresh
run planned 9 phases (11 after replans), executed for ~12 minutes, reported
`✓ Assessment complete — 45 total finding(s)`, and then broke. Artifacts: `/tmp/step2-rerun.log`.

What broke and what is now fixed:

- **Fixed — master-key cache expiry killed finalization.** `EncryptionManager.CACHE_TTL_MS` is 5
  minutes and the run was 12, so the cached key was gone by teardown. `EngagementStore._getEngagementDb()`
  is synchronous and only consulted `getCachedMasterKey()`, so it threw
  `Cannot open encrypted engagement <id>: master key not loaded` — the findings were never written and
  the per-engagement `findings` table stayed empty. Added `EncryptionManager.loadKeySync()` (a
  read-only keychain reload that never mints a key) and used it in both encrypted open paths.
- **Fixed — the same failure hung the CLI.** `store.saveFindings()` ran inside the runner's `finally`
  block ahead of `await bridge.disconnect()`; when it threw, `disconnect()` was skipped and the MCP
  worker child process kept the event loop alive forever (process sat at ~0% CPU after the error).
  Teardown now persists inside its own `try`, disconnects regardless, and reports a persistence failure
  as the run's error so an unattended driver exits non-zero instead of "succeeding" over an empty DB.
- **Fixed — the TS planner scheduled tools the worker disabled or whose flags were broken.**
  Phase selection is TS-side, so worker-side `phases=[]` did not stop dispatch: the run attempted
  `dnsx`, `gospider`, `github-endpoints -json`, `amass -json`, `chaos`, `uncover`, `cloud_enum`,
  `s3scanner`, `shuffledns`, `masscan` and collected a usage error for each. The worker now publishes
  its per-tool verdict over MCP (`disabled`/`disabled_reason`/`pipeline_step`/`available`),
  `ToolRegistry.setWorkerToolStatus()` applies it before dispatch, and the broken invocations are
  corrected or explicitly disabled. See §3 for the mechanism and the remaining provisioning gap.
- **Fixed — `auth_detection` FAILED on a target with no auth surface.** `register`/`login` reported
  `FORM_NOT_FOUND`, which is the *expected* result against the fixture (it has no registration or
  login form), but the executor counted it as an error and failed the whole phase. Failures that
  mean "the target does not have the thing you asked for" (`FORM_NOT_FOUND`, `NO_CREDENTIALS`,
  `EMAIL_EXISTS`) are now classified as expected absences: recorded on `executor.expectedAbsences`
  and reported as an observation, with the phase completing cleanly. A genuine failure still fails.
  `credential_replay`'s "Unknown tool" is fixed by its registration in the MCP registry (§3).
- **Fixed — registry drift is resolved, not just reported.** The four live tools the MCP worker had
  that the TS registry lacked (`finding_verifier`, `playwright-bola`, `playwright-privesc`,
  `playwright-xss`) were added to `tool-definitions.yaml` (with a new `finding_verification`
  capability), and the SAST/SCA capability gaps were aligned. The three pipeline steps the TS
  registry had that the MCP lacked are now registered *and* published as disabled, so they are
  neither "missing" nor dispatchable. Drift comparison now ignores worker-disabled tools on both
  sides — the report is empty: `missing_from_registry: []`, `missing_from_mcp: []`,
  `capability_gaps: []`.
- **Fixed — log noise.** The credentials warnings were one per `load()` call (~36 per run) and fired
  whenever the master-key *cache* was cold rather than when the file was actually plaintext;
  `CredentialStore` now uses `loadKeySync()` and warns once per path per kind, and only after
  checking the file really is plaintext. `[replan-rules] Unknown subtype` is deduplicated per
  subtype and silent for informational recon subtypes (`OPEN_PORT`, `HTTP_ENDPOINT`,
  `CRAWLED_ENDPOINT`, `technology_detection`, `raw_output`, `port_open`, `web_vulnerability`). The
  workflow loader no longer parses `tool-definitions.yaml`/`approval-policies.yaml` as workflows and
  logs them as unparseable on every run.
- **Addressed — destructive-tool gating was unproven under `ARGUS_AUTO_APPROVE=1`.** Every gate
  decision is now recorded (`ApprovalService.decisions`, echoed as an `[approval] …` line and
  summarized into the engagement audit log as `APPROVAL_DECISIONS`), so an unattended run shows the
  gates were consulted rather than silently bypassed. `ARGUS_DENY_DESTRUCTIVE=1` makes destructive
  gates and destructive tools refuse even with auto-approve on, which is what allows the block path
  to be exercised end-to-end in an unattended run.

### 3. Tool availability is operationally incomplete

**Fixed (2026-09-30):** the registry no longer *reports* tools it actually has. A hand-written
entry that re-registered a name used to replace the generated definition wholesale, dropping the
`binary` its YAML declares; the MCP bridge then asked PATH for a binary that was never meant to
exist and skipped the tool as "unavailable" — `browser_security_operator` and `register` among
16 that now resolve (`1b7fff82`). The 8 steps the orchestrator runs in-process (`report-generator`,
`post_exploitation`, `intelligence-engine`, …) are now declared as pipeline steps instead of being
reported as missing binaries (`7f800a33`).

**Fixed (2026-09-30, scanner correctness):** three definitions invoked flags their installed binaries
reject, so the tools reported success while scanning nothing — `dalfox --json` (removed in dalfox v2,
which also requires the `url` subcommand), `gitleaks --source <URL>` (gitleaks scans filesystem paths,
not URLs), and nikto losing the target's port to the URL normaliser, which made it scan `:80`. Nikto
also wrote its `-Format json` report to a `nikto_<host>_<timestamp>.json` file in the current
directory rather than stdout, littering the working tree; it now prints to stdout and the parser
reads the text report.

**Fixed (2026-09-30, empty results read as errors):** a tool that exited 0 without printing
anything was reported as a failure. The worker maps a clean exit to `success: true` with no
structured data and no `error`, while the executor's result handling only accepted structured
findings or a non-empty raw string — so a legitimately empty result fell through to
`Tool returned unsuccessful result`, was retried once, and was counted as an error. On the
`127.0.0.1` demo run this produced `recon … 25 finding(s), 3 error(s)`, where all three errors were
`alterx`, `waybackurls`, and `subfinder` (confirmed against the live worker: each returns
`success=True` with no data, because the target has no subdomains, no archived URLs, and no
permutable labels). A clean exit with no output is now a terminal empty result — no retry, no
error, and no `expectedAbsences` entry.

Confirming that, a second and separate problem surfaced: the installed `waybackurls`
(tomnomnom/waybackurls v0.1.0) is a silent no-op. It exits 0 in ~0.2 s with no output for a domain
whose CDX query returns rows — the same
`cdx/search/cdx?url=iana.org*&output=text&fl=original&collapse=urlkey` request returns results from
`curl` in the same shell, and clearing proxy variables changes nothing, so it never completes a
query. It must be verified or dropped: now that an empty result is correctly treated as success, a
tool that never queries anything will *report* success and contribute nothing. The health probe
cannot catch this, because it only checks that `--help` exits 0 (which it does).

The same pass found the worker only converted *System A* parser output. The ~30 parsers under
`parsers/parsers/` (System B — httpx, katana, naabu, gau, dalfox, trivy, bandit, subfinder, …)
return plain dicts, while the MCP result builder reads `finding.__dict__`; every finding from those
tools turned the whole run into `'dict' object has no attribute '__dict__'` instead of a finding.
System B output is now converted to `NormalizedFinding`, so those tools deliver findings on the MCP
path for the first time.

**Fixed (2026-09-30, recon invocation pass):** every YAML-defined tool was also written inline in
`tool_definitions.py`, and the inline copies won wholesale. They turned out to be the staler copies,
so the effective registry silently lost data the YAML carried:

- `httpx` lost `target`'s `-u` flag, so the URL was appended positionally — ProjectDiscovery httpx
exits 0 with **no output** for a bare positional URL, which is indistinguishable from "no findings".
- The 17 launcher tools lost the `extra` parameter, so the `--extra` credentials-JSON fix in the
YAML never reached the MCP bridge and credentialed phases still failed on argv.
- `cloud_metadata_probe` lost `--extra`; `testssl` lost `jsonfile`.

`_register()` now merges a re-registration with its YAML definition: parameters the inline entry
omits are appended, a same-named parameter that lost its CLI flag regains it, and `binary`/empty
`default_args`/unset metadata are inherited. Inline policy still wins where it is deliberate
(phases, args, timeout, `requires`) — nmap stays disabled, the SAST tools stay out of HTTP phases,
and the playwright scheme gate is not resurrected.

The verification (running each tool through `MCPServer.call_tool`, the path the worker uses) also
found several invocations that were wrong independently of the merge:

- **Tool PATH shadowing:** the execution PATH put the venv first, and `venv/bin/httpx` is the
*Python* HTTPX CLI. The availability check looked in `~/go/bin` and passed, then execution ran the
Python CLI and failed with `Usage: httpx [OPTIONS] URL / Error: No such option: -s`. `~/go/bin` now
precedes the venv, and discovery and execution share one `_augmented_tool_path()` (so
`ARGUS_EXTRA_PATH` is honored by both).
- **Inherited stdin:** `alterx` switches to stdin mode when stdin is any pipe, even at EOF, and then
reports ``[FTL] alterx: no input found`` despite `-l`. Scanner subprocesses now get
`stdin=DEVNULL`.
- **Stale flags:** nuclei v3 removed `-json` (→ `-jsonl`, now 11 findings on the fixture); whatweb
rejects `--format=json` and Ruby WhatWeb's `--log-json` (both text and JSON formats are now parsed,
so it yields a finding); gospider's `-j` is an unknown shorthand (→ `--json`); alterx dropped `-d`
(→ `-l`).
- **Disabled for cause, like nmap:** `dnsx` (v1.2+ requires `-w` with `-d`, or a list file/stdin,
neither of which the arg builder can supply) and `gospider` (the installed build segfaults in an
ioctl path and otherwise exits 0 with no output — a silent no-op success). Both keep their
corrected flags so a newer build only needs the phase re-enabled.

Live result for the recon set (`MCPServer.call_tool` against the local fixtures): httpx, katana,
whatweb, wafw00f, nikto (5 findings), naabu, nuclei (11), alterx (111) and ffuf all run and parse;
subfinder runs but external sources exceed 60 s (network-bound, not a flag bug); amass was not run
(600 s budget); masscan, shuffledns, chaos, cloud_enum, uncover, s3scanner and github-endpoints need
root, credentials or external APIs — their built argv was verified, execution was not.

**Fixed (2026-09-30, target_kind):** path-only tools are now defined with `target_kind: path` in
their YAML (`semgrep`, `bandit`, `pip-audit`, `npm-audit`, `gitleaks`, `trivy`, `trufflehog`,
`gosec`, `brakeman`, `govulncheck`, `phpcs`, `eslint`, `spotbugs`, `dependency_check`,
`ai-surface`), and `MCPServer.call_tool` refuses a scheme-bearing URL *before* spawning anything:
``Tool 'gitleaks' scans filesystem paths (target_kind=path); it cannot be handed the URL ...``.
The rule deliberately allows bare host-shaped values, because govulncheck takes Go module paths and
trivy takes image references such as `registry.example.com/image:tag`; only URLs with an explicit
scheme are rejected. The TS planner already excludes `supports_web: false` tools from web targets —
this closes the same hole on the execution path. The YAML value survives the inline overrides
because the merge treats `target_kind: any` as unset.

**Fixed (2026-09-30, worker tool state reaches the planner):** *reporting* availability was not
enough, because the run still dispatched tools the worker could not run. Phase selection happens on
the TypeScript side, so `phases=[]` in `tool_definitions.py` had no effect at all: the run attempted
`dnsx` and `gospider` (both deliberately disabled) and every tool whose binary is absent, then
tallied each refusal as a phase error — recon came back `28 finding(s), 13 error(s)`.

`MCPServer.get_tools()` now publishes the worker's verdict on every entry — `disabled` +
`disabled_reason` (no execution phase, missing `required_env` API key, in-process pipeline step),
`pipeline_step`, and `available` (binary present on the *execution* PATH, the same augmented PATH
the subprocess receives). `MCPServer` also overlays the declarative registry on the YAML files, so
`credential_replay`/`post_exploitation`/`internal_probe` exist (they had been called as "Unknown
tool" because they have no YAML file) and the disabled state from `tool_definitions.TOOLS` is
applied to the YAML-derived entries.

On the TS side `ToolRegistry.setWorkerToolStatus()` records that snapshot and `selectBest()`,
`getToolsByCapability()` and the executor's `pipelineSteps` path all refuse a blocked tool. The
workflow runner applies the snapshot immediately after `bridge.connect()` and writes the result to
the engagement audit log as `TOOL_AVAILABILITY`. Live on this machine that is 29 tools skipped with
a reason, and the MCP drift report is now empty on all three lists (previously
`missing_from_registry: [finding_verifier, playwright-bola, playwright-privesc, playwright-xss]`,
`missing_from_mcp: [post_exploitation, credential_replay, internal_probe]`, plus 5 capability gaps —
the four live tools were added to the TS registry and the SAST/SCA capabilities aligned).
`scripts/argus-worker-status-check.ts` reproduces that check against the real worker.

**Fixed (2026-09-30, usage-failure invocations):** the tools that failed on their own arguments are
now either corrected or explicitly disabled, so the planner stops scheduling them:

- `github-endpoints` had no `-json` flag and no input flag for its target — the URL was passed
positionally. `-d` is now the target flag; it is disabled unless `GITHUB_TOKEN` is set.
- `shuffledns` has no `-json` and cannot run without a resolvers file (`-r`), which Argus does not
ship — disabled.
- `masscan` needs root for raw sockets and a port range the planner never supplies — disabled;
naabu covers port scanning.
- `cloud_enum` was passed `--json`, which its argparse rejects before scanning (the usage error that
was in the log); the keyword is the only required input.
- `amass` was invoked with `-json`, which the installed build does not define. The inline entry that
overrode the YAML also carried the stale `enum -json`, so it was removed entirely and the YAML is
now the only definition.
- `s3scanner` was passed the bucket name positionally → "exactly one of: -bucket, … required"; the
target now carries `-bucket`.
- `chaos` and `uncover` read their key from the environment and were attempted with none set. YAML
tools can now declare `required_env:`; when a listed variable is unset the tool is published as
disabled instead of the run collecting "PDCP_API_KEY not specified".

A YAML file can also declare `disabled: true`, which is the only way to express `phases=[]`: an
empty `phases:` key is falsy and the generator re-derived the phases from the tool's capabilities.

What remains is provisioning, not reporting: 13 third-party binaries are genuinely absent here
(`testssl`, `wpscan`, `trufflehog`, `commix`, `jwt_tool`, `brakeman`, `spotbugs`, `phpcs`, `eslint`,
`dependency_check`, `sn1per`, `bucket_upload`, `ai-surface`), and the bridge names them in one
warning per run. External binaries such as Nuclei, Nmap, SQLMap, WhatWeb, Subfinder, and others
still depend on host or container provisioning.

The provisioning system exists, but deployment readiness still depends on:

- installing the binaries,
- verifying versions and checksums,
- ensuring templates and data are present,
- testing the exact target environment,
- making missing-tool behavior visible and intentional.

## Major feature gaps

### 4. Rich TUI architecture is incomplete

The TypeScript Argus layer exists, but the target architecture is not fully realized.

Notably:

- `src/argus/tui/app.tsx` is absent.
- Some routes exist as CLI alternatives rather than full TUI routes.
- Settings, terminal, rich asset/evidence browsing, and complete report UX remain partial or deferred.
- OpenCode runtime remnants and branding remain in parts of the TUI.

### 5. Report export is incomplete

The HTML renderer exists, but the full export architecture still needs end-to-end verification:

- dedicated exporter behavior,
- complete `--format` handling,
- `--open` browser behavior,
- JSON/Markdown/HTML consistency.

### 6. Attack-chain visualization is mostly a plan

The backend attack graph exists, but the documented interactive visualization is not fully implemented or proven:

- no proven complete Python-to-TUI visualization bridge,
- no fully verified interactive graph UI,
- no complete chain drill-down and evidence experience,
- no proven real-time chain-discovery rendering.

### 7. Advanced security tools are not all implemented

The advanced-tools plan describes approximately 14 composite systems, including:

- browser security operator,
- attack-surface mapper,
- evidence intelligence engine,
- threat-intelligence aggregator,
- vulnerability knowledge engine,
- finding-correlation engine,
- attack-path generator,
- infrastructure-security analyzer,
- assessment orchestrator,
- verification agent,
- workflow analytics,
- engagement analytics.

Some primitives and similarly named modules exist, but the complete composite architecture described in the plan is not fully implemented and verified.

## Security and autonomy limitations

### 8. Active-defense resilience is unproven

The adversarial evaluation plan is not an executed test system. The following remain unproven against real defended targets:

- WAF detection and adaptive behavior,
- rate-limit compliance,
- honeypot and deception detection,
- prompt-injection handling from target content,
- gradual target degradation,
- large-response and data-flood handling.

### 9. Exploitation and lateral movement remain limited

Argus supports post-exploitation concepts and attack-chain planning, but true fleet-scale red teaming is not yet a first-class workflow.

Remaining limitations include:

- single-target-centric orchestration,
- incomplete multi-host asset-graph execution,
- limited lateral-movement automation,
- limited session rotation,
- no generalized adaptive-encoding pipeline,
- no robust blockade/deception model,
- exploit scripts that may be generated but are not universally executed as verified actions.

### 10. Evidence chain-of-custody is incomplete in depth

Hashing and integrity verification exist, but complete forensic-chain proof still needs operational validation for:

- operator identity,
- source-tool and phase metadata in every path,
- parent-finding relationships,
- append-only and auditable event history,
- signed authenticity rather than integrity-only hashes,
- encrypted artifact lifecycle and recovery.

**Encryption at rest leaks and destroys in practice (2026-09-30).** Three concrete failures, all
reproduced locally:

- **Plaintext leaks.** 822 non-empty `engagement.db.decrypted` files were found under
  `~/.argus/engagements/`. `EncryptedDbHandle` decrypts to that temp path on open and only removes it
  on a clean `close()`; any crash or SIGTERM (both of which happened during these runs) leaves the
  engagement database in plaintext on disk. Startup should sweep `*.decrypted` / `*-enc.tmp` leftovers.
- **The test suite destroys the operator's real master key.** `test/argus/helpers/encryption-test-utils.ts`
  calls `EncryptionManager.destroy()` + `initialize()` against the shared `argus`/`master-key` keychain
  entry, so every test run rotates the key that real encrypted engagements and evidence packages were
  written with — they become permanently undecryptable. Tests must use a separate keychain service and
  an isolated `ARGUS_DATA_DIR`.
- **No data-dir isolation.** `StoragePaths.basePath` resolves to `~/.argus`, and the suites never set
  `ARGUS_DATA_DIR`, so tests write into the operator's real data directory: 8,723 engagement
  directories have accumulated. This also makes the encryption integration tests order-dependent —
  `encryption-workflow.test.ts` > "preserves phases, status transitions, and workflow snapshots in
  encrypted engagements" fails in a full-file run and passes in isolation.

Operator impact: a test run during this investigation left `ENG-muoa5y14-1k` undecryptable
(verified: it opened before the run and fails with `Unsupported state or unable to authenticate data`
after). Findings loss was nil (the run above never persisted any), but the
mechanism is data-destroying and should be fixed before any external demo.

**Fixed (2026-09-30).** The three failure modes above no longer reproduce:

- **Keychain namespace isolation.** `storage/encryption.ts` now resolves the keychain identity per
  call via `keychainServiceName()` / `keychainAccountName()` (`ARGUS_KEYCHAIN_SERVICE` /
  `ARGUS_KEYCHAIN_ACCOUNT`), with `usesIsolatedKeychain()` to detect a non-production namespace.
  `test/preload.ts` sets `ARGUS_DATA_DIR` to a temp directory and `ARGUS_KEYCHAIN_SERVICE` to
  `argus-test-<pid>` before any module loads, and destroys that test key in `afterAll`.
  `encryption-test-utils.ts` gained `assertIsolatedKeychain()`, which throws if a test tries to
  `initialize()`/`destroy()` the encryption manager against the production entry — so a future test
  cannot silently reintroduce the rotation.
- **Plaintext sweep.** `EncryptedDbHandle` now exports `sweepEngagementScratchFiles()` /
  `sweepEngagementsDir()` and sweeps `*.decrypted` / `*.decrypted-wal` / `*.decrypted-shm` /
  `*.encrypting` in `_open()` **before both** the create-fresh and open-existing branches (a stale
  plaintext file reused by the create branch previously produced `SQLITE_NOTADB: file is not a
  database`), and uses the same helper on `close()`. Those per-handle sweeps are immediate, since
  the caller holds that engagement open and any scratch copy of it is stale by definition.
  `workflow-runner.ts` additionally sweeps `StoragePaths.engagementsDir` as a Step 0 before creating
  the engagement, so a normal run self-heals leftovers from a previous crash — but that
  directory-wide pass skips scratch files younger than 60 seconds
  (`MIN_DIRECTORY_SWEEP_AGE_MS`), so a concurrently running session cannot have its working
  plaintext file deleted out from under it.
- **Startup key rotation / hang.** `EngagementStore.syncEncryptionFromConfig()` no longer calls
  `ensureKeySync()`. It uses `loadKeySync()` and, when no key is present, degrades to
  `encryptionEnabled = false` with a one-time stderr warning naming the keychain service/account and
  `argus encryption init`. This removes the path that minted a replacement key on a failed keychain
  read and — on macOS — blocked indefinitely in the keychain authorization dialog
  (`SecKeychainAddGenericPassword → defaultKeychainUI → AuthorizationCopyRights`). Ordinary commands
  such as `argus engagements` no longer hang; `ensureKeySync()` is now documented as explicit-init-only.

Verification: the production fingerprint (`service=argus account=master-key`, sha256 prefix
`30af2c50e8a451b0`) is identical before and after running the encryption suites; `~/.argus/engagements`
held 8,972 entries throughout. The focused encryption files pass 87/87, and the full `test/argus/`
suite is now **1,451 pass, 2 skip, 0 fail** (baseline before this work: 1,438 pass / 3 fail / 2 skip) —
the previously hanging `engagements handles empty state gracefully` and `llmStatus reflects crash when
worker exits immediately` tests now pass. Residual: the 961 stale `.decrypted` files already under
`~/.argus` are removed by the next run's Step 0 sweep (they are hours old, so the 60-second grace
period does not spare them), and engagements encrypted with the old (pre-rotation) master key
remain permanently undecryptable — that part is irreversible.

### 11. Production LLM reliability is not proven at scale

Fallbacks and retry logic exist, but these areas remain insufficiently validated:

- malformed JSON and tool-call recovery under real provider responses,
- rate-limit handling across providers,
- provider failover,
- token and cost accuracy,
- long-running context retention,
- prompt-injection resistance against adversarial target data,
- degraded-mode reporting visible to operators.

## Testing and CI gaps

### 12. CI does not yet prove a clean full suite

The randomized collection-order job is currently non-blocking:

```yaml
continue-on-error: true
```

It reports fragility but does not block merges.

The standard CI path also excludes or schedules separately:

- database tests,
- Redis tests,
- E2E tests,
- Docker tests,
- fixture and full-matrix tests.

This is operationally reasonable, but it is not equivalent to proving that all tests pass on every change.

### 13. Skips, xfails, and xpasses need cleanup

The 55 skipped and 7 xfailed tests need classification into:

- intentionally environment-gated,
- obsolete,
- genuinely unsupported,
- or blocked by incomplete CI setup.

The 27 xpasses should be reviewed and either:

- converted into normal passing tests,
- or made strict so regressions become visible.

### 14. Benchmark and soak validation remain incomplete

Infrastructure exists for:

- false-negative benchmarking,
- long-run drift testing,
- memory, cost, and quality monitoring.

Ground-truth manifests, real target runs, and validated baseline results are still missing.

## Documentation and governance

### 15. Documentation is labeled but not fully normalized

All current documentation files have current-status notices, but many historical documents still contain stale internal claims and counts. They are clearly labeled as historical, yet remain confusing unless individually rewritten or archived.

### 16. Governance is documented, not operationally enforced

The following still require real organizational action:

- signed authorization workflow,
- incident-response rehearsal,
- dated reviewer sign-off,
- license and legal review,
- retention-policy enforcement review,
- insurance and liability decisions,
- third-party penetration testing,
- organizational readiness review.

## Practical completion order

The highest-value sequence is:

1. Make collection-order behavior deterministic and remove the remaining full-suite failures.
2. Establish a reproducible, clean CI baseline across the relevant service-backed suites.
3. Prove the complete scan path with provisioned binaries against controlled vulnerable targets.
4. Verify automatic deep-scan, auth-scan, exploitation, replanning, and reporting dispatch.
5. Execute active-defense, false-negative, and long-run soak evaluations.
6. Finish or explicitly narrow the TUI, report-export, and attack-visualization scope.
7. Convert governance templates into executed organizational controls.

Until these items are closed with source-level and runtime evidence, Argus should be described as a substantial security-assessment platform with partial autonomous capabilities—not as fully autonomous red-team software.