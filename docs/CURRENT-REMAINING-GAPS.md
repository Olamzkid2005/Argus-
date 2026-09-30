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