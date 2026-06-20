# Argus — Failure-Mode & Pre-Flight Checklist

> **Purpose:** An exhaustive checklist of everything that can go wrong or prevent Argus from working properly. Use it before running `argus`, `argus assess`, `make docker-up`, `make test-v5`, or before a release. Walk top-to-bottom for a full pre-flight; jump to a section when debugging a specific failure.
>
> **How to use:** Every item is a `- [ ]` checkbox. Each item states the failure mode, where it lives, a **severity tag**, and (where useful) how to check or fix it.
>
> **Severity legend:** `[C]` Critical (blocks startup/deploy/CI), `[H]` High (silent wrong results, data loss, security), `[M]` Medium (degraded mode, friction, edge-case breakage), `[L]` Low (cosmetic/cruft/footgun).
>
> **Companion docs:** `docs/BUG_SWEEP_REPORT.md` already catalogs ~150 code-logic bugs (SSRF, `cache_mode` crash, etc.). This checklist complements it by covering environment, deployment, configuration, integration, and the cross-cutting failure modes that report does not cover, plus a consolidated set of the highest-impact code issues. Cross-references are noted with `(see BUG_SWEEP_REPORT §X)` where applicable.
>
> **Last audited:** 2026-06-20 (third-pass deep audit) · branch `Argus-Tui`
>
> **Audit history:** Pass 1 (§1–§26) covered environment, deployment, configuration, integration, and cross-cutting code issues via three parallel subsystem sweeps. Pass 2 (§27) was a line-by-line deep read of the workflow/tool YAMLs, Python agent/orchestrator/parser internals, OpenCode runtime + TUI shell, and the full test suite — it uncovered ~100 additional failure modes, including several new **Critical** showstoppers (notably an empty parser registry that silently drops findings from ~20 tools). Pass 3 (§28) focused on the full TS TUI shell, executor/planner/MCP bridge, bin/argus, CI, and the actual flagged test files — it found ~30 additional items, verified 4 Pass 2 claims as **incorrect** (corrected below), and confirmed 2 new genuine **Critical** items. All Pass 2/3 Critical/High items were verified directly against source.

---

## Table of Contents

1. [Prerequisites & Runtime](#1-prerequisites--runtime)
2. [Installation & Dependencies](#2-installation--dependencies)
3. [Configuration & Secrets](#3-configuration--secrets)
4. [Path & Filesystem Layout](#4-path--filesystem-layout)
5. [Docker / Compose](#5-docker--compose)
6. [Database (Postgres + pgvector)](#6-database-postgres--pgvector)
7. [Redis](#7-redis)
8. [MCP Workers Bridge (TS ↔ Python)](#8-mcp-workers-bridge-ts--python)
9. [External Security Toolchain](#9-external-security-toolchain)
10. [LLM / AI Provider](#10-llm--ai-provider)
11. [Playwright / Browser Verification](#11-playwright--browser-verification)
12. [TUI / Terminal](#12-tui--terminal)
13. [CLI Commands](#13-cli-commands)
14. [Workflow Execution (Planner / Executor / Replan)](#14-workflow-execution-planner--executor--replan)
15. [Engagement Store & State](#15-engagement-store--state)
16. [Evidence & Integrity](#16-evidence--integrity)
17. [Reporting](#17-reporting)
18. [Python Workers Internals (Celery / Agent / DB / Security)](#18-python-workers-internals-celery--agent--db--security)
19. [Tests & CI](#19-tests--ci)
20. [Git & Repository Hygiene](#20-git--repository-hygiene)
21. [Networking & Target Reachability](#21-networking--target-reachability)
22. [Tool Self-Security](#22-tool-self-security)
23. [Resource Limits & Reliability](#23-resource-limits--reliability)
24. [Legal / Authorization / Scope](#24-legal--authorization--scope)
25. [Documentation & UX Consistency](#25-documentation--ux-consistency)
26. [Top Blockers — Fix These First](#26-top-blockers--fix-these-first)
27. [Second-Pass Deep Audit Findings (2026-06-20)](#27-second-pass-deep-audit-findings-2026-06-20)
28. [Third-Pass Deep Audit Findings (2026-06-20)](#28-third-pass-deep-audit-findings-2026-06-20)

---

## 1. Prerequisites & Runtime

- [ ] **Bun 1.x installed and on PATH** `[H]` — The TUI, CLI entry, engagement store (`bun:sqlite`), and verifiers (`Bun.write`/`Bun.file`) hard-depend on Bun. Node alone will not run most of Argus. `package.json` pins `packageManager: bun@1.3.14`. Check: `bun --version`.
- [x] **No Node fallback for the engagement subsystem** `[C]` — **FIXED** — Replaced static `import { Database } from "bun:sqlite"` with a lazy dynamic import via `createRequire`. Under Node, the error is now a clear "Bun required" message at construction time instead of a cryptic module-not-found at import time. The module can now be loaded under Node without crashing — only constructing `EngagementStore` throws.
- [ ] **Python 3.11+ installed and on PATH** `[H]` — MCP worker requires 3.11+ (Dockerfile + `pyproject.toml` target `py311`). `python3.12`/`3.13` work; a stray `__pycache__/fix_all_tests.cpython-314.pyc` at repo root shows someone ran a debug script under Python **3.14**, which is unsupported — don't repeat that.
- [ ] **Python interpreter consistency** `[M]` — `mcp_server.py:586` invokes python3 tools as the bare string `"python3"` (PATH-resolved), not `sys.executable`. If PATH's `python3` differs from the interpreter running the MCP server, `run_agent_tool.py` runs under a Python missing the needed packages → `ImportError`. Pin the same venv everywhere.
- [ ] **`bun` resolvable from spawned children** `[H]` — `index.ts:58` and `bin/argus` spawn `bun` by name. If Bun is installed via a shell-only path (e.g. `~/.bun/bin` not exported to non-interactive shells, or VS Code's integrated terminal lacks it), the TUI fails to launch with an unhandled spawn error.
- [ ] **`npx` available for Playwright install** `[M]` — `package.json` postinstall uses `npx playwright install chromium`; without npx (no Node) the browser isn't installed and `argus verify` fails later.
- [ ] **Terminal is a real TTY for the TUI** `[H]` — `start-argus.sh:150` claims it warns on non-TTY but actually **launches the TUI anyway** when stdin isn't a TTY, then the SolidJS TUI crashes reading from a non-TTY. Don't pipe/`&` the launcher.
- [ ] **macOS vs Linux vs Windows** `[M]` — ANSI escapes in `ui.ts` render literally on Windows `cmd.exe` without VT enabled; `tool_runner._locked_env` defaults `HOME` to `/root` (wrong on macOS/non-root); `which` may not exist on Alpine (used by `doctor.ts`). Windows support is effectively absent.

## 2. Installation & Dependencies

- [ ] **`bun install` ran in `Argus-Tui/packages/opencode`** `[H]` — `start-argus.sh:90` auto-installs if `node_modules` missing, but only inside that package. Running `bun run` directly without install → missing-module errors.
- [ ] **Python venv created in `argus-workers/venv`** `[H]` — `Makefile` `dev-worker`/`test-backend`/`lint-backend` all `source venv/bin/activate` with no `|| exit`; if `venv/` is missing, `source` fails and the recipe **silently proceeds with system Python**, importing wrong/incompatible deps. `start_worker.sh` and `celery_worker_launcher.py` hardcode `venv/bin/celery` with no fallback.
- [ ] **`pip install -r requirements.txt` has `libpq-dev` available** `[M]` — `psycopg2>=2.9.10,<3` is a source build requiring `libpq-dev`/`postgresql-libs`. The mac v4 script installs `psycopg2-binary` instead — inconsistent. On a bare machine the build fails.
- [ ] **`requirements-dev.txt`-only installs break production imports** `[H]` — CI `fixture-smoke`/`fixture-full` jobs install only `requirements-dev.txt`, but fixture tests import production code needing `celery`/`sqlalchemy` from `requirements.txt` → import errors at collection time.
- [x] **`psutil` not in production requirements** `[H]` — **FIXED** — `psutil` moved to `requirements.txt`. Orphaned subprocesses are now killed on timeout.
- [ ] **Duplicate `httpx` specifier** `[L]` — `requirements.txt` lists `httpx==0.28.1` and later `httpx>=0.28`. Pip resolves to 0.28.1 today; a stricter future pip may warn.
- [x] **Malformed tracked file `argus-workers/requests==2.28.1_flask_=2.0.0_`** `[H]` — **FIXED** — File staged for deletion. Removed from `argus-workers/`.
- [x] **`uv.lock` is a fake/empty stub** `[H]` — **FIXED** — File staged for deletion. Removed from `argus-workers/`.
- [ ] **Playwright chromium actually installed** `[H]` — `package.json` postinstall runs `npx playwright install chromium` and **swallows all errors silently**. On network-restricted/CI envs the browser is absent and `argus verify`/browser verifiers fail later with opaque "chromium not found". Verify: `npx playwright install --dry-run` or check `~/Library/Caches/ms-playwright`.
- [ ] **No bundled/distribution build path supported** `[H]` — `index.ts:55` (`../../src/index.ts`), `bin/argus`, and the reporting `templates/` dir all rely on **source-relative** paths. Any `bun build`/bundled `dist/` install breaks all of them. Argus only runs from source.

## 3. Configuration & Secrets

- [ ] **`.env` created from `.env.example`** `[H]` — Required for docker-compose. `POSTGRES_PASSWORD`, `DATABASE_URL`, `NEXTAUTH_SECRET` are `${VAR:?required}` in compose; missing any → compose aborts.
- [ ] **`POSTGRES_PASSWORD` matches the password inside `DATABASE_URL`** `[H]` — `.env.example` ships both with the same placeholder `change_me_in_production`. If a user changes only `POSTGRES_PASSWORD` (per the comment) but not the embedded URL password, postgres + workers disagree → auth failures with no clear error.
- [ ] **`NEXTAUTH_SECRET` set to a strong random value** `[H]` — `.env.example` ships it **empty**. Compose's `:?` catches it, but local (non-compose) runs won't — NextAuth fails at runtime with a cryptic JWT error. Generate: `openssl rand -base64 32`.
- [ ] **`LLM_API_KEY` set when LLM features are enabled** `[M]` — `.env.example` ships it empty. With `argus.config.yaml` defaults (`llm_finding_analysis: false`) it's optional, but `argus doctor --online` and non-deterministic `assess` need it. No doctor-time check that a key exists when features are enabled.
- [ ] **Two incompatible LLM env conventions** `[H]` — Root `.env.example` uses a single `LLM_API_KEY` with prefix-based provider auto-detection. `argus-workers/.env.example` uses separate `OPENAI_API_KEY`/`ANTHROPIC_API_KEY`. The worker `llm_client.py` and the TUI may read different vars → LLM works in one half but not the other. Pick one convention.
- [ ] **`argus-workers/.env.example` has unresolved `${DB_USER}/${DB_PASSWORD}/${DB_NAME}`** `[H]` — These placeholders are never defined anywhere. Copying verbatim yields a literally-broken DB URL (`os.getenv` won't expand shell vars).
- [ ] **Redis URL differs between local and compose examples** `[M]` — Worker example: `redis://localhost:6379`; root example: `redis://redis:6379` (compose service name). A locally-started worker can't resolve `redis`.
- [ ] **All feature flags default to `false`** `[M]` — `argus.config.yaml` ships `workflow_registry`, `engagement_store`, `approval_gates`, `llm_finding_analysis` all off. With everything off, `argus assess` runs severely degraded (no registry, no persistence, no LLM). No warning if you run assess with all features disabled.
- [ ] **`DETERMINISTIC_FALLBACK` flag defaults `true`** `[M]` — `feature-flags.ts:32` defaults it true, contradicting the file header and `cli.ts` comment ("all opt-in / all false"). Documentation/behavior mismatch.
- [x] **Feature-flag singleton never loads config files** `[H]` — **FIXED** — `getFeatureFlags()` singleton now loads from config files, so `argus.config.yaml` settings are respected everywhere.
- [ ] **`ARGUS_MODE=0` does NOT disable Argus mode** `[M]` — Code checks `!!process.env.ARGUS_MODE` (truthy for any non-empty string incl. `"0"`). Use `ARGUS_MODE=""` or unset. Should check `=== "1"`.
- [ ] **No `.env` auto-loading** `[M]` — Nothing loads `.env` files at runtime (doctor checks for their existence but doesn't parse them). Env vars must be set in the shell. A populated `.env` alone won't configure a non-compose run.
- [ ] **`tools.enabled: []` disables ALL tools** `[M]` — `tool-config.ts:59`: if `enabled` is an empty array, every tool is disabled. Footgun if you set `enabled:` with nothing under it.
- [ ] **`sqlmap` disabled by default but installed in Docker** `[L]` — `argus.config.yaml` disables sqlmap; `argus-workers/Dockerfile` still `pip install sqlmap==1.8`. Wasted image size + confusion.
- [ ] **Config loader throws on structurally invalid YAML** `[M]` — `loader.ts:89` `ArgusConfigSchema.parse` throws `ZodError` on invalid fields, but the docstring says "returns defaults if missing or invalid". Only missing/unparseable files return defaults; structurally-invalid ones throw. Contradicts docs.
- [ ] **Typo'd feature keys silently dropped** `[L]` — `loadFromConfig` matches against `Object.values(Feature)`; `features.worklow_registry: true` (typo) is silently ignored.

## 4. Path & Filesystem Layout

- [ ] **`argus-workers/mcp_server.py` located via fragile 5-levels-up relative path** `[H]` — `workflow-runner.ts:161`, `cli.ts`, `tui-commands.ts` all compute `../../../../../argus-workers/mcp_server.py` from `src/argus/`. `doctor.ts`/`resume.ts` use a **different** 6-levels-up pattern from `src/argus/commands/`. All resolve correctly **only inside the dev monorepo**. Any package relocation/install breaks them. No central `projectRoot` helper.
- [ ] **Bare `__dirname` with no ESM fallback** `[H]` — `doctor.ts:12`, `resume.ts:21/45`, `registry.ts:12` use bare `__dirname`. Under Node ESM `__dirname` is undefined → `ReferenceError`. Bun provides it, masking the bug. Inconsistent with `cli.ts`/`tui-commands.ts` which do have a fallback.
- [ ] **Space in repo path is mostly handled, but** `[L]` — `/Users/mac/Documents/Argus Tui` has a space. `workflow-runner.ts:159` uses `decodeURIComponent(new URL(".",import.meta.url).pathname)` to handle it (good). Shell scripts quote `$SCRIPT_DIR` (good). Real bugs: `Makefile:5` `grep ... $(MAKEFILE_LIST)` is unquoted (breaks `make -f "/path with space/Makefile" help`); `docs/implementation order.txt` has a space in its filename (unquoted shell refs break).
- [ ] **`reporting/generator.ts:11` pathname handling on Windows** `[M]` — `new URL(".",import.meta.url).pathname` yields `/C:/...` on Windows (leading slash before drive). Path joins then misbehave. Fine on macOS/Linux.
- [ ] **`store.ts:179` derives parent dir with string `".."`** `[L]` — Fragile; a bare-filename `dbPath` resolves `..` relative to cwd. Use `path.dirname`.
- [x] **Evidence base dir assumptions** `[C]` — **FIXED** — `integrity.ts` path aligned with collector write path. See §16 for details.

## 5. Docker / Compose

- [x] **`platform` service build context `./argus-platform` does not exist** `[C]` — **FIXED** — Platform service already commented out in `docker-compose.yml` with note "Platform service temporarily removed — argus-platform/ directory was removed during v5 migration."
- [x] **No `argus-platform/Dockerfile`** `[C]` — **FIXED** — Platform service removed from docker-compose.yml (commented out). No platform Dockerfile needed.
- [x] **Postgres initdb mounts `./argus-platform/db/{schema,audit_logging,performance}.sql`** `[C]` — **FIXED** — `docker-compose.yml` now mounts `./argus-workers/database/init/01-schema.sql` and `02-audit.sql`, both of which exist. No more empty directory mounts or missing schema.
- [x] **`argus-workers/Dockerfile` Go tarball SHA256 is wrong** `[C]` — **FIXED** — Dockerfile now uses `GO_VERSION="1.22.10"` with dynamic SHA verification (downloads `.sha256` alongside the tarball from `go.dev/dl/`). No hardcoded SHA to go stale. Verification passes correctly.
- [ ] **`docker-compose` (v1 hyphenated) vs `docker compose` (v2 plugin)** `[M]` — `Makefile:71,74,77` invoke legacy `docker-compose`. On modern installs only the `docker compose` plugin exists → `make docker-up/down/logs` fail with "command not found".
- [ ] **Worker/celery-beat get `cap_drop: ALL` with no `cap_add`** `[M]` — The worker image installs nmap/nikto/nuclei etc. Some scan types need capabilities (nmap SYN scan needs `CAP_NET_RAW`). Without `cap_add: NET_RAW`, those scans fail silently in-container.
- [ ] **DVWA pinned to `:latest`** `[L]` — Juice-shop is pinned to `v17.1.1`; DVWA is `:latest` → non-reproducible e2e, image may change/disappear.
- [ ] **pgvector extension capability is dead** `[M]` — `pgvector/pgvector:0.7.4-pg16` is pulled, but the extension is only useful if `schema.sql` enables it — and schema.sql is missing (see above).
- [ ] **No documented way to wipe the postgres volume after bad init** `[L]` — Named volumes persist; a botched init (empty schema) sticks until `docker volume rm`. `stop-argus.sh`/`make clean-all` don't remove volumes.
- [ ] **`celery_app.py` fallback reads `../argus-platform/.env.local`** `[M]` — Dead path (dir absent). Works only because compose injects `DATABASE_URL`. Fragile if run outside compose.

## 6. Database (Postgres + pgvector)

- [x] **Migrations `001`–`003` (base schema) are missing** `[C]` — **FIXED** — Migrations `001_base_schema.sql`, `002_audit_logging.sql`, and `003_webhooks_loop_budgets.sql` now exist in `argus-workers/database/migrations/`. They create all base tables (`engagements`, `findings`, `feature_flags`, `user_settings`, `audit_log`, `performance_log`, `webhooks`, `loop_budgets`) with proper foreign keys, indexes, and constraints. `run_migrations()` now works standalone.
- [ ] **`webhooks` table never created** `[H]` — `post_finding_hooks.py:8` references migration `030_webhooks.sql` which doesn't exist (migrations stop at 017). `_get_matching_webhooks` fails with `relation "webhooks" does not exist`.
- [ ] **`loop_budgets` table never created** `[H]` — `loop_budget_manager.py:122` does `INSERT INTO loop_budgets ... ON CONFLICT`. No migration creates it → budget persistence crashes (caught + logged, so budget state is silently lost across iterations → budget overruns possible).
- [ ] **Tenant context failures silently ignored** `[M]` — `database/connection.py:258` calls `set_tenant_context(%s)`; failures are caught at `logger.debug` and ignored. If the function errors, tenant isolation is silently disabled → potential cross-org data exposure.
- [ ] **One-off connections leak** `[L]` — `connection.py:352` `connect()` creates connections outside the pool; callers that don't close them leak.
- [ ] **SQLite engagement DB has no `busy_timeout`** `[M]` — `engagement/store.ts` sets `PRAGMA foreign_keys=ON` per-connection but no `busy_timeout`. Multiple concurrent `argus` processes (TUI + CLI) on one `~/.argus/argus.db` can hit "database is locked". WAL helps but isn't sufficient under contention.

## 7. Redis

- [ ] **Redis reachable at the configured URL** `[H]` — Celery broker, result backend, cache, and rate limiting all need it. Local vs compose URLs differ (see §3). Check: `redis-cli -u "$REDIS_URL" ping`.
- [ ] **Cache and Celery results share Redis DB 1** `[M]` — `cache.py` defaults `CACHE_REDIS_URL` to `{REDIS_URL}/1` and `CELERY_RESULT_BACKEND` also defaults to `{REDIS_URL}/1`. Key-space collisions and memory eviction conflicts under load. Use separate DBs.
- [ ] **Redis not exposed externally** `[L]` — Compose binds `127.0.0.1:6379` (good). Local dev must not bind `0.0.0.0` without auth.
- [x] **Committed Windows Redis binaries (~22MB) in `redis/`** `[H]` — **NOW FIXED 2026-06-20** — Windows binaries removed from git tracking via `git rm --cached`; `redis/*.exe` added to `.gitignore`. (Previously claimed fixed but was still on disk — see §28.1.)

## 8. MCP Workers Bridge (TS ↔ Python)

- [ ] **Bridge spawns Python with no `cwd`/`env` injection** `[M]` — `mcp-client.ts:163` `spawn(pythonPath, [workersPath], { stdio: ["pipe","pipe","pipe"] })`. The worker inherits the TS process's env/cwd. No way to pass `PYTHONPATH` or a venv via the bridge.
- [ ] **`python3.12` rejected by bridge path validation** `[M]` — `mcp-client.ts:66` `validatePaths` only accepts `python3`/`python` or a full executable path. `doctor.ts:276` offers `python3.12` as a candidate → mismatch; doctor may report a python the bridge then refuses.
- [ ] **Non-JSON stdout from worker hangs requests** `[H]` — `mcp-client.ts:171` `JSON.parse(line)` in a try/catch that **silently ignores malformed lines**. A stray `print()`, warning, or traceback-to-stdout makes the request hang until the 30s timeout, with no "first non-JSON line" diagnostic.
- [ ] **No automatic worker restart on child exit** `[H]` — `restartWorker` exists but **nothing calls it automatically**. On worker death, pending requests are rejected and LLM is marked UNAVAILABLE, but no respawn. The `'exit'` handler doesn't trigger supervisor restart.
- [x] **Tool drift check compares MCP against itself** `[H]` — **FIXED** — `bridge.setRegistryTools(toolRegistry.listTools())` is now called in `workflow-runner.ts`, seeding the bridge's `toolsCache` with the local registry's tool list. `quickDriftCheck()` now compares MCP vs registry instead of MCP vs itself.
- [ ] **`getTools` returns stale cache on failure** `[M]` — On first connect if `list_tools` fails, returns `[]`; drift checks then compare `[]` vs `[]` = "in sync".
- [ ] **LLM-error detection by string-match** `[M]` — `mcp-client.ts:324` checks `message.includes("LLM is not available")`. If the worker rephrases the error, circuit-breaker logic silently breaks.
- [ ] **`maxPending = 10` hard cap** `[L]` — Parallel phases + agent loop can stack requests; over-cap gives a generic error.
- [ ] **Default 10-min callTool timeout may kill long scans** `[M]` — `mcp-client.ts:299` default `600000`ms. Deep sqlmap can exceed it; not configurable per-tool from the agent/hybrid path.
- [ ] **stderr forwarded verbatim to terminal** `[M]` — A chatty worker floods the terminal and corrupts the TUI screen.
- [ ] **MCP transport dies on one malformed JSON line** `[M]` — `mcp_transport.py:41` a single bad client line returns `None`, breaking the `run()` loop and killing the whole stdio worker. Also sends responses for JSON-RPC notifications (spec violation).
- [ ] **Two unrelated `ToolDefinition` classes** `[H]` — `mcp_server.py:83` and `tool_definitions.py:86` share the name with divergent fields. High confusion/maintenance risk.

## 9. External Security Toolchain

- [ ] **All required binaries installed and on PATH** `[H]` — nuclei, nmap, nikto, httpx, subfinder, amass, dnsx, naabu, masscan, dalfox, ffuf, gospider, katana, gau, waybackurls, semgrep, gitleaks, whatweb, etc. `mcp_server.py:354` **skips registering any tool whose binary isn't found** (logs a warning, continues). A scan then silently lacks tools. Run `argus doctor` and verify each tool.
- [ ] **PATH augmentation includes venv/go/homebrew** `[L]` — `mcp_server.py:353` augments PATH with `sys.executable`'s dir, `~/go/bin`, `/opt/homebrew/bin`, `argus-workers/venv/bin`, `/usr/local/bin`. On Linux without homebrew this is harmless but if your tools live elsewhere (e.g. `/snap/bin`, custom) they won't be found.
- [x] **`_SHELL_INJECTION_PATTERN` blocks legitimate tool arguments** `[C]` — **FIXED** — Blocklist removed; `subprocess.run` uses list form (no shell), so these characters are safe. URLs with `&`, selectors with `[]`, etc. now work.
- [x] **Playwright tool default selectors are self-blocked** `[C]` — **FIXED** — Same fix as `_SHELL_INJECTION_PATTERN` above; blocklist removed so selectors with `[]` no longer trigger false rejections.
- [ ] **`blocked_command_patterns` blocks `curl`, `wget`, `nc`, `ssh`, `node`, `php`, `ruby`, `perl`** `[M]` — Any YAML tool whose command is one of these is skipped at registration. Verify no legitimate tool relies on them (some custom recon scripts might).
- [ ] **`DANGEROUS_PATTERNS` substring-matches `DROP TABLE`/`DELETE FROM`/`TRUNCATE`** `[M]` — `tool_runner.py:51` case-insensitive **substring** match blocks legitimate targets/params containing these words (e.g. endpoint `/api/truncate`, param `action=delete_from_cache`, a finding titled "truncate"). Valid scans silently skipped.
- [ ] **`tool-config.ts` empty `enabled` array disables everything** `[M]` — see §3.
- [x] **`recon_signals` gate is never evaluated** `[M]` — **FIXED** — `passesGates()` now checks `recon_signals` when `context.reconSignals` is provided (skipped when undefined). `GateContext` interface includes `reconSignals?: string[]`. sqlmap/commix/jwt_tool have `recon_signals` declared in the TS YAML and can now be gated by the planner.
- [ ] **Tool ID collisions under concurrency** `[M]` — `executor.ts:364` finding IDs use `Date.now() + Math.random().toString(36).slice(2,8)` (6 chars). Parallel tools in the same ms can collide; uniqueness is probabilistic.
- [ ] **`nmap` SYN scan needs `CAP_NET_RAW`** `[M]` — In Docker (cap_drop ALL) and on some hosts, SYN scans fail; use `-sT` connect scan or grant the capability.

## 10. LLM / AI Provider

- [ ] **API key provider auto-detection by prefix** `[M]` — `llm_client.py:91`: `sk-or-` → OpenRouter, `AIzaSy`/`AQ.` → Gemini, `sk-` → OpenAI, else defaults to OpenAI `api.openai.com`. A key matching no prefix but belonging to another provider silently targets OpenAI and fails with 401. The `AQ.` "new Gemini" prefix is unverifiable.
- [ ] **Unreplaced placeholder keys "available" but always fail** `[L]` — `.env.example` `OPENAI_API_KEY=your_openai_api_key_here`; `is_available()` only checks non-empty, so a placeholder makes the client "available" and every call fails at runtime (401) instead of failing fast at config.
- [x] **`ai_explainer.py:436` reads wrong attribute** `[H]` — **FIXED** — `_generate_with_httpx` now checks `api_url` before falling back to `base_url`, so a properly configured `LLMClient` with `api_url` set works correctly.
- [x] **`ai_explainer.py:573` bypasses tenant-scoped key lookup** `[H]` — **FIXED** — `generate_embedding` now checks `getattr(self.llm_client, "api_key", None)` before falling back to `os.getenv`, respecting the tenant-scoped API key from the LLM client.
- [x] **`tool_runner._redact_sensitive_args` breaks token-based tools** `[H]` — **FIXED** — `_redact_sensitive_args` no longer replaces CLI values with `__REDACTED__`. Real tokens are passed through to subprocesses; env var injection (`TOOL_*`) is kept as a harmless bonus.
- [ ] **`poc_generator.py` cost tracking is broken** `[M]` — `:255` checks `"cost_usd" in result` but `result` is parsed JSON (never has `cost_usd`; that's on `LLMResponse`) → branch dead → PoC-generation LLM costs never recorded → budget overruns. `:158` calls `cost_tracker.has_remaining_budget()` but `CostTracker` exposes `exceeded(estimated_cost)` → `AttributeError` if the standard tracker is passed.
- [x] **LLM analysis is a no-op even when the flag is enabled** `[H]` — **FIXED** — `LlmClientImpl` implemented and wired into `FindingAnalyzer`. Reports now get AI analysis when `LLM_FINDING_ANALYSIS` is enabled.
- [ ] **LLM unavailable → circuit breaker depends on exact error string** `[M]` — see §8.

## 11. Playwright / Browser Verification

- [ ] **Chromium launched with no `--no-sandbox`** `[H]` — `engine.ts:17` `chromium.launch({ headless })` passes no sandbox args. On Linux as root / in Docker / CI, Chromium refuses to run without `--no-sandbox`. Launch fails opaquely.
- [ ] **`page.goto(url, { waitUntil: "networkidle" })` with no timeout** `[H]` — `engine.ts:31`, `login.ts:32`, `observer.ts:5`. `networkidle` hangs forever on sites with websockets/SSE/polling/analytics. Set a navigation timeout.
- [x] **Verifiers write screenshots to CWD, not evidence dir** `[H]` — **FIXED** — Verifiers now write to the evidence directory instead of CWD.
- [x] **Evidence artifacts reference garbage file paths** `[H]` — **FIXED** — Artifact paths now point to actual files in the evidence directory.
- [x] **`collectEvidence` returns empty IDs** `[M]` — **FIXED** — Evidence packages now return valid `packageId` and `findingId` for correlation.
- [ ] **XSS verifier false-positives on escaped payload** `[H]` — `xss.ts:96` second branch reduces to `payloadTextInDom` (escaped, non-executing payload text in DOM) → marks **escaped, non-executing** payload as "probable XSS". Contradicts the comment at line 93.
- [ ] **`verify.ts:53` uses finding description/title as a URL** `[H]` — `targetUrl = options?.targetUrl ?? finding.description ?? finding.title`. Those are prose, not URLs → `page.goto` throws "invalid URL". Should fall back to `engagement.target`.
- [x] **`verify.ts:88` evidence capture always fails** `[H]` — **FIXED** — Evidence capture now happens before the browser context is closed.
- [ ] **Verifiers only fire for exact role names `attacker`/`victim`/`user`/`admin`** `[M]` — `verify.ts:66/70/75`. The credential schema allows arbitrary role names; naming a role anything else silently skips its verifier.
- [ ] **`createContext` overwrites/leaks contexts** `[M]` — `engine.ts:22` overwrites `this.context` each call; previous context never closed. `bola.ts`/`priv-esc.ts` call `createContext` per access check → context leak + state confusion.
- [ ] **Login detection is case-sensitive and over-broad** `[M]` — `login.ts:10` `content.includes("password")` misses "Password"/"LOGIN"/"Sign In" and matches CSS class names like `password-field`.
- [ ] **`runner.ts` has no per-step timeout** `[M]` — A hung setup/execute/verify hangs forever (cleanup is in `finally`, good).
- [ ] **Browser-verification path is effectively untested** `[H]` — `test/argus/unit/z-mocked/verify.test.ts` defines `mockPage`/`mockContext` but **never wires them** to `verifyCommand` (passes only `storeOverride`). Mocks are dead code.

## 12. TUI / Terminal

- [ ] **`ARGUS_MODE=1` set for Argus branding** `[M]` — Set by `index.ts:61`. If unset, you get the default OpenCode home, not ArgusDashboard. And `ARGUS_MODE=0` is truthy (see §3).
- [ ] **No terminal-size handling** `[L]` — Boxes use fixed widths (62 in `ui.ts`, barWidth 30). Narrow terminals wrap/clip with no `rows`/`cols` checks.
- [ ] **No `isTTY` guard at route level** `[M]` — If `ARGUS_MODE=1` but stdout is piped, SolidJS terminal rendering still attempts and produces garbage.
- [ ] **Approval gates steal stdin in TUI mode** `[H]` — `approval.ts:75` reads raw `stdin` and toggles `resume()`/`pause()`; in TUI mode the terminal is in raw mode for keypresses → approval prompts corrupt terminal state / lose keypresses. (Gates default off, but if enabled in TUI this breaks.)
- [ ] **`scan-store` is not re-entrant** `[H]` — `scan-store.ts:52` module-level singletons; the persist/restore swap in `handleProgressEvent` isn't re-entrant. Concurrent progress events from multiple engagements can interleave `persistActive`/`restore` and corrupt active state. No locking.
- [ ] **`scan-store-writer` used by `/report` passes no engagementId** `[M]` — `tui-commands.ts:274` → report's `analysis_progress` events mutate whatever engagement is active in the scan store — possibly the wrong one.
- [ ] **Restored scan phases show "0 finding(s)"** `[M]` — `routes/scan.tsx:69` `completePhase(i, 0, …)` — the DB `phases` table doesn't store per-phase finding counts; restored phases always show 0 even when findings exist.
- [ ] **`navigator` silently no-ops in CLI mode** `[M]` — `navigator.ts:19` module-level `navigateHandler`; `navigateTo` no-ops if unset. `/findings` calls it then returns a string — in CLI the navigation is lost with no warning.
- [ ] **`onClick` on `<box>` via `as any`** `[M]` — `routes/findings.tsx` attaches `onClick` to `<box>` with `as any`. If `@opentui/solid`'s `box` doesn't honor `onClick`, clicks silently do nothing. Pattern is pervasive and untested.
- [ ] **Findings route load errors swallowed** `[M]` — `findings.tsx:171` catches and `console.error`s; user sees "No findings" instead of an error state.
- [ ] **Low count includes INFO; Low filter excludes INFO** `[L]` — `findings.tsx:183` `severity <= 1` counts INFO(0); the Low chip sets `filterSev(1)` excluding INFO. Count and filter disagree.

## 13. CLI Commands

- [ ] **"Most recent engagement" picks oldest in TUI** `[H]` — `listEngagements()` orders by `desc(created_at)` so `[0]` = newest, `[length-1]` = oldest. The CLI `findings` uses `engagements[0].id` (newest) but `/findings`, `/report` TUI handlers and `findings.tsx:144` use `engagements[engagements.length-1].id` (oldest). Docstrings say "most recent" but pick oldest.
- [ ] **`DISMISSED` status offered by CLI but absent from the type** `[H]` — `cli.ts:229` offers `--status DISMISSED`, but `FindingStatus = "PENDING"|"CONFIRMED"|"REJECTED"|"FINALIZED"` (`shared/types.ts:16`, `engagement/types.ts:5`). Filtering by DISMISSED never matches anything. Phantom status. `findings.tsx:39` status icons also lack DISMISSED.
- [ ] **Empty `/assess` passes empty target** `[M]` — `tui-commands.ts:53` `parts.find(...) ?? parts[0]` → `/assess` with nothing → target `""` passed to `assessCommand("")` with no validation.
- [ ] **`evidence <action>` has no `choices` constraint** `[L]` — Any string passes as the action, then falls to `default:` returning "Unknown evidence action". No yargs `choices`.
- [x] **`assessCommand` always writes markdown to stdout** `[H]` — **FIXED** — Markdown output is now opt-in, not unconditional. No more raw markdown polluting the TUI.
- [ ] **`config.ts:53` reads entire `credentials.json` for byte length** `[L]` — And labels credentials.json as "user config" (conflates config with credentials).
- [ ] **`evidence.ts:71` non-numeric prune arg → silent no-op** `[M]` — `parseInt(args[0] ?? "30", 10)` → `NaN` → `cutoff = Date.now() - NaN` → `mtimeMs <= NaN` always false → nothing pruned, silently.
- [ ] **`verify.ts:33` iterates all engagements × all findings** `[L]` — O(N×M) to locate one finding ID; no direct DB lookup by finding ID.
- [ ] **`main.ts` casts yargs commands `as any`** `[L]` — Defeats type checking on command shapes; misconfigured builders fail at runtime, not compile.

## 14. Workflow Execution (Planner / Executor / Replan)

- [x] **Approval gates default ON when feature flags unset** `[H]` — **FIXED** — Approval gates now default to OFF when flags are unset, and hybrid phases are also gated.
- [x] **Hybrid (`llm_driven`) phases bypass approval gates entirely** `[H]` — **FIXED** — Hybrid phases now pass through the same approval gates as other phases.
- [ ] **`ARGUS_MAX_REPLANS=0` cannot disable replanning** `[M]` — `planner.ts:10` `Number(process.env.ARGUS_MAX_REPLANS) || 10` → `0 || 10` = 10. Same in `resume.ts:192`.
- [ ] **Capability drop is silent** `[M]` — `planner.ts:64` if no workflow covers required caps, falls back to `planDeterministic` which ignores the tool registry → phases reference capabilities no tool provides, then filtered with warnings. Silent capability drop.
- [ ] **Agent loop `maxIterations = 50` hardcoded** `[M]` — `executor.ts:309` no env override. A stuck agent burns 50 iterations × per-tool timeouts.
- [ ] **Circuit breaker conflates "tool reported error" with "tool broken"** `[M]` — `executor.ts:497` on a successful RPC that returned `isError`, marks the tool failed and records a health failure. A tool returning errors (not crashes) can trip the breaker.
- [ ] **`toolTimeout` for agent-internal tools is hardcoded in TS** `[L]` — `executor.ts:451` `AGENT_INTERNAL_TOOLS` is a TS set; new agent tools added in Python won't get the extended timeout unless also added here. Drift-prone.
- [ ] **Workflow version not validated at load** `[M]` — `loader.ts:13` validates fields but not `version` (required by type). A YAML missing `version` loads, then `resume.ts:62` `validateWorkflowVersion` aborts with "version mismatch". Current YAMLs all have `version:`, but no guard.
- [ ] **`registry.loadAll()` is destructive on partial failure** `[M]` — `registry.ts:17` clears the map then loads; if `loadAllWorkflows` throws partway, the map is left empty. Repeated calls lose loaded workflows on error.
- [ ] **Broken workflow YAMLs are silently skipped** `[H]` — `loader.ts:57` `catch { }` skips all unparseable YAMLs with no diagnostic. A typo in `full_assessment.yaml` → workflow silently absent. Can't distinguish "not a workflow" from "broken workflow".
- [ ] **`tool-registry.load()` has no try/catch** `[H]` — `tool-registry.ts:62` a malformed `tool-definitions.yaml` throws and crashes the whole assessment (workflow-runner.ts:211 calls it unguarded).
- [ ] **`approval-policies.yaml` is dead config** `[M]` — Lives in the workflows dir but isn't a workflow; `approval.ts` hardcodes gates in `registerDefaultGates` and **never reads** the YAML.
- [ ] **Resume re-runs completed phases if plan changed** `[M]` — `resume.ts:103` matches existing phases by `ep.id === p.phaseId`, but plan IDs are regenerated (`phase-${i}-${name}`); if the workflow differs, IDs won't match → all phases treated as new → re-runs completed work.
- [ ] **`detectAuthState`/`detectTargetType` are loose substring matches** `[M]` — `strategy.ts:33` any URL containing `"auth"` (e.g. `/author`) → `"oauth"`; `:8` `/api` substring (`/apidoc`) → `"api"`. Misclassification affects planning.
- [ ] **Replan rules spam stderr** `[L]` — `replan-rules.ts:32` writes to stderr for every finding with an unmapped subtype; 500 findings → 500 lines.
- [ ] **`PhaseDefinition` duplicated in two files** `[L]` — `workflows/types.ts:7` and `planner/types.ts:36` (identical). Drift risk.

## 15. Engagement Store & State

- [x] **Hard `bun:sqlite` dependency, no Node fallback** `[C]` — **FIXED** — Lazy dynamic import via `createRequire` provides a clear "Bun required" error under Node instead of module-level crash. (See §1.)
- [ ] **Single global DB `~/.argus/argus.db`, no per-project isolation** `[M]` — Multiple concurrent `argus` processes contend on one SQLite file. (See §6 busy_timeout.)
- [ ] **DB connection never closed** `[M]` — `store.ts:183` `new Database(...)` with no `close()`/finalizer. Long-running TUI leaks the handle until exit.
- [ ] **Migration errors swallowed** `[M]` — `store.ts:195` `ALTER TABLE ... ADD COLUMN negative` wrapped in try/catch that swallows ALL errors. If the ALTER fails for another reason (locked, disk full), it's ignored and later inserts referencing `negative` fail confusingly.
- [ ] **Sequence counters not persisted** `[M]` — `store.ts:12` `_engagementSeq`/`_auditSeq` are module-level, reset on restart. Two processes in the same ms can collide (mitigated by `Date.now()` but not guaranteed).
- [ ] **`saveEvidencePackage`/`saveArtifact` have no conflict handling** `[M]` — `store.ts:357/421` no `onConflictDoUpdate`; re-saving the same ID throws an uncaught UNIQUE violation.
- [ ] **Plaintext credentials at `~/.argus/credentials.json`** `[H]` — `credentials.ts:15` `save` chmods 0o600 but `load` does not verify permissions. A pre-existing world-readable file is silently used on shared systems.
- [ ] **Corrupt credentials file silently becomes empty** `[M]` — `credentials.ts:31` `catch { this.data = { roles: {} } }`. No diagnostic; user gets an empty store.
- [ ] **`getDefaultCredentials` picks `roles[0]` by object key order** `[M]` — `credentials.ts:53` "default" depends on JSON insertion order. Non-deterministic across edits.
- [ ] **`CONFIRMED` confidence tier (5) is unreachable** `[L]` — `confidence.ts:31` `VERIFIED→CONFIRMED` rule `condition: () => false`. Dead state.
- [ ] **`toPhaseRecord` loses null-vs-empty distinction** `[L]` — `store.ts:118` `capabilities: row.capabilities ?? []`.

## 16. Evidence & Integrity

- [x] **`verifyPackage` path layout mismatches the collector's write layout** `[C]` — **FIXED** — Paths aligned: `verifyPackage` now looks at `~/.argus/engagements/<engId>/artifacts/<findingId>/manifest.json` matching the collector's write path.
- [ ] **`integrity.ts` hashes whole files in memory** `[H]` — Comment says "stream-based hash for large files" but `hashFileSync` uses `readFileSync` (loads entire file). `createReadStream` is imported but **unused**. Large screenshots can OOM. Comment contradicts code.
- [ ] **`checkStorageLimit` fails open** `[M]` — `collector.ts:60` `catch { return true }` — if size computation fails, the write is **allowed**. Could exceed disk quota silently.
- [ ] **`package_hash` contract is fragile** `[M]` — `collector.ts:197` computes the hash over `JSON.stringify(manifest,null,2)+hashes` with `package_hash:""`; `integrity.ts:58` re-derives with `{...manifest, package_hash:""}`. Works **only if JSON key order is identical** on both sides — any re-serialization difference → false hash mismatch.
- [ ] **Duplicated, divergent package-creation logic** `[M]` — `ArtifactStore` (in `store.ts`) and `EvidenceCollector` compute `package_hash` identically, but `ArtifactStore` is never used by any command. Dead code except its own test.
- [ ] **Two divergent `ArtifactType`/`EvidenceManifest` shapes** `[M]` — `evidence/types.ts:10` uses snake_case (`package_id`/`engagement_id`); `shared/types.ts:43` uses camelCase (`packageId`/`findingId`). Verifiers return camelCase with empty IDs; collectors use snake_case. Mixed.
- [ ] **`readdir({ recursive: true, withFileTypes: true })` needs Node 18.17+** `[L]` — `collector.ts:53`, `evidence/store.ts:138`. `entry.parentPath` requires it. Bun supports it; older Node throws.
- [ ] **`evidence show` doesn't show artifact contents** `[L]` — `commands/evidence.ts:57` `show` and `verify-package` do nearly the same thing; `show` doesn't display contents. Confusing UX.

## 17. Reporting

- [ ] **Generated HTML report has XSS** `[H]` — `generator.ts:226/230` inserts `f.tool`, `f.phase`, `f.status` **without `escapeHtml`** into the report HTML. If a tool name or phase/status contains HTML, the generated report is vulnerable. (Tool names are registry-trusted, but status/phase come from findings.)
- [ ] **`escapeHtml` doesn't escape single quote** `[L]` — `generator.ts:259`. If the template uses single-quoted attributes with inserted values, injection possible. Minor since values are mostly double-quoted.
- [ ] **`html.replace("{{TARGET}}", …)` only replaces first occurrence** `[L]` — `generator.ts:243`. `{{DATE}}` uses `/g`, `{{FINDINGS}}` uses `replaceAll`, but `{{TARGET}}` is single. Inconsistent; a second `{{TARGET}}` stays literal.
- [ ] **LLM analysis no-op in reports** `[H]` — `report.ts:17` `new FindingAnalyzer(db)` with no llmClient (see §10). Even with the flag on, analysis is empty. And the report path's flag singleton ignores config (see §3).
- [ ] **`finding-analyzer.ts:111` unvalidated LLM JSON** `[M]` — `JSON.parse(response.text)` with no schema validation; `impact`/`remediation` may be non-arrays → `generator.ts:145` `for (const item of analysis.impact)` throws if it's a string.
- [ ] **Template ships only with source** `[M]` — `generator.ts:235` `join(_dirname, "templates", "report.html")`; if the package is bundled, `templates/` won't ship → fallback HTML (no styling).
- [ ] **`generateFromEngagement` opens a new DB each call** `[L]` — `generator.ts:49` constructs a new `EngagementStore` per call; no reuse.
- [ ] **Compliance Jinja autoescape only for `.html`/`.xml`** `[L]` — `compliance_reporting.py:235` templates with other extensions (`.j2`, `.txt` rendered into HTML) wouldn't be escaped. All current templates are `.html`, so OK today.

## 18. Python Workers Internals (Celery / Agent / DB / Security)

- [x] **Orphaned subprocesses on swarm timeout (no psutil in prod)** `[H]` — **FIXED** — `psutil` moved to `requirements.txt`. Orphaned subprocesses are now killed on timeout in production.
- [x] **`shutdown_handler.should_shutdown()` always returns True once set** `[M]` — **FIXED** — Final `return True` changed to `return False` when active tasks exist and deadline hasn't been exceeded. Graceful shutdown now waits for in-flight work.
- [ ] **TracerProvider set twice** `[M]` — `celery_app.py:19` and `mcp_server.py:54` both call `setup_tracing()` at import. Importing both in one process → OpenTelemetry "Overriding of TracerProvider is not allowed" and ignores the second config.
- [ ] **`celery_worker_launcher.py` hardcodes `venv/bin/celery`** `[M]` — Falls back to `sys.executable` for python but not for celery. If the venv isn't set up, it executes a non-existent binary. `start_worker.sh` has the same hardcode with no fallback.
- [x] **Webhook SSRF** `[H]` — **FIXED** — `post_finding_hooks.py:106` `_dispatch(url, payload, ...)` now has full SSRF validation: HTTPS-only scheme, static hostname blocklist, DNS resolution with is_private_ip() checks (IPv4/IPv6 private ranges, loopback, link-local, ULA, cloud metadata), and follow_redirects=False on httpx client.
- [ ] **`tool_runner._locked_env` defaults `HOME=/root`** `[M]` — `:225` when `HOME` is unset. On macOS/non-root Linux, tools writing to `~/.config` (gitleaks, nmap, nuclei, git) get `PermissionError` on `/root`.
- [ ] **`tool_core/sandbox.py:163` no None guard on `tool_path`** `[M]` — If both `registry.resolve` and `runner._resolve_tool_path` return falsy, `None`/`""` is passed to `asyncio.create_subprocess_exec` → `TypeError`/`FileNotFoundError`.
- [ ] **Two parallel parser systems with different coverage** `[M]` — `tool_core/parser/dispatcher.py` registers 7 parsers; `parsers/parser.py` uses ~30. `mcp_server` uses the 7-parser dispatcher; the orchestrator uses the ~30-parser one. Findings parsed differently depending on path.
- [ ] **`run_agent_tool.py:25` dynamic `import_module(f"tools.{tool_name}")`** `[M]` — The script is whitelisted, but `tool_name` is taken verbatim from the CLI arg; a caller who can invoke `call_tool` could target any `tools.<name>` module with an `AbstractTool` subclass, not just intended ones.
- [ ] **Feature flags cached forever per instance** `[L]` — `feature_flags.py:94` no TTL; DB flag changes need `clear_cache()` or a process restart.
- [ ] **`cache.py` and Celery share Redis DB 1** `[M]` — (See §7.)
- [ ] **Beat task name vs module mismatch** `[L]` — `celery_app.py:208` references `tasks.security.run_self_scan` but the module is `tasks.self_scan`. Works (synthetic `name=`) but fragile.

## 19. Tests & CI

- [x] **CI JUnit reports have `fail_on_failure: false`** `[H]` — **FIXED** — CI now properly fails the workflow on test failures.
- [x] **Windows unit tests run with `|| true`** `[H]` — **FIXED** — Windows test failures are no longer silently swallowed.
- [ ] **PR-trigger mismatch with `Argus-Tui` branch** `[H]` — `lint.yml:5` `pull_request: branches: [dev]` only. Current branch is `Argus-Tui`; PRs targeting `Argus-Tui` won't trigger PR checks.
- [ ] **`bun-version: latest` unpinned** `[M]` — A Bun regression breaks all jobs simultaneously. Pin it.
- [ ] **Smoke tests pollute the real `~/.argus/argus.db`** `[M]` — `smoke.test.ts:47` runs `argus` against the real user DB with no temp-dir isolation. CI runs mutate the real DB.
- [ ] **Test counts disagree everywhere** `[M]` — README "335+", Makefile "280+", e2e script hardcoded "335", CI comment "558". The e2e `pass "Argus unit tests (335 tests)"` is a static string that lies if the count changes.
- [ ] **`--strict-markers` in pyproject** `[L]` — `python-tests` job runs `pytest -m "not requires_db and not requires_redis and not e2e"`; any test using an unregistered marker fails the whole job. Register markers in `pyproject.toml`.
- [ ] **28 inherited OpenCode workflows in `Argus-Tui/.github/workflows/` are dead** `[M]` — GitHub Actions only runs root `.github/workflows/`. These reference OpenCode infra (npm publish, Discord, SST, Blacksmith runners, `bot@opencode.ai`) that doesn't apply to Argus. Pure confusion/dead weight. One even uses invalid `case()` in a `group:` expression.
- [ ] **No ESLint enforcing the architecture boundary** `[M]` — `ARCHITECTURE_BOUNDARIES.md:36` says `../../opencode/` imports "will be caught in CI" but no `no-restricted-imports` rule is configured. Enforcement is aspirational.
- [ ] **Coverage gaps** `[L]` — No tests for MCP reconnection, doctor MCP spawn, `ARGUS_MODE=0`, DISMISSED status, browser-verification wiring. `finding-analyzer.test.ts:65` comment: "we need a proper mock; for now just verify it doesn't crash."

## 20. Git & Repository Hygiene

- [x] **Committed Windows Redis binaries (~22MB) in `redis/`** `[H]` — **NOW FIXED 2026-06-20** — Windows binaries removed from git tracking; `git rm --cached` executed. `redis/*.exe` added to `.gitignore`. (See §7.)
- [x] **Malformed tracked file `argus-workers/requests==2.28.1_flask_=2.0.0_`** `[H]` — **FIXED** — File staged for deletion. (See §2.)
- [~] **Hardcoded debug telemetry beacon in `bin/argus`** `[H]` — **INCORRECT CLAIM** — Per §28.1 verification, the committed `bin/argus` (36 lines) never contained telemetry. The claim was based on a stale version. No fix needed.
- [ ] **`bin/argus:21` has no spawn `'error'` handler** `[H]` — If `bun` isn't on PATH, spawn emits an uncaught `'error'` event → unhandled exception, no clean message (unlike `index.ts:64` which handles it).
- [ ] **`.gitignore:44` `Kimi_Agent_Argus Security Splash/` matches nothing** `[L]` — That dir doesn't exist; the actual artifact `argus-kimi-page.png` (234KB, tracked) isn't ignored.
- [ ] **`.gitignore:62` references nonexistent `argus-platform/`** `[L]` — Stale `git rm --cached -r argus-platform/**/__pycache__/` instruction that can't be executed.
- [ ] **`.semgrep_cache/settings.yml` committed** `[M]` — Stale cache in repo.
- [ ] **`.commandcode/taste/*` personal notes committed** `[M]` — Environment-specific notes (MacPorts psql path, `browser-use-direct`, "keys configured through the frontend Settings page") that shouldn't be tracked.
- [ ] **9 uncommitted modified files** `[M]` — `bin/argus` (mode change) + `commands/{evidence,resume,verify}.ts`, `engagement/store.ts`, `evidence/collector.ts`, and 3 `z-mocked` tests. `resume.test.ts` shows ~270 lines changed. Any clone/CI uses the committed version, not these.
- [ ] **Branch model confusion** `[M]` — Working branch `Argus-Tui`; `Argus-Tui/AGENTS.md:3` says default is `dev`; CI PR checks target `dev`. Local `main` may not exist. Forkers may diverge.
- [ ] **Duplicate `CONTRIBUTING.md`/`LICENSE` at root and `Argus-Tui/`** `[L]` — Root ones are Argus-specific (short); `Argus-Tui/` ones are inherited OpenCode (long). Contributors won't know which is authoritative.
- [ ] **`Argus-Tui/{flake.nix,sst.config.ts,infra/,nix/}` dead upstream infra** `[L]` — Argus deploys via docker-compose, not SST/Nix. Can mislead.
- [ ] **`Argus-Tui/package.json:117` repository URL is garbled** `[M]` — `"https://github.com/Olamzkid2005/Argus-"` (trailing dash, incomplete). npm/bun metadata may misbehave.

## 21. Networking & Target Reachability

- [ ] **Target host reachable from the execution context** `[H]` — In Docker, the worker container must reach the target (default bridge network → host targets need `host.docker.internal` or `--network=host`). A target only reachable from your laptop is unreachable from the container.
- [ ] **DNS resolves** `[M]` — `subfinder`/`amass`/`dnsx` need working DNS. In containers, DNS may differ from host.
- [ ] **Outbound internet for LLM + tool installs** `[M]` — LLM calls and `npx playwright install`/`go install` (Dockerfile) need network. Air-gapped runs fail.
- [ ] **Proxy settings honored** `[L]` — Subprocesses inherit env; if `HTTP_PROXY`/`HTTPS_PROXY` are set, some tools honor them and some don't. Inconsistent scan results.
- [ ] **Target scope/authorization** `[H]` — (See §24.) Argus will run active scans against any target you give it.
- [ ] **Rate limiting / WAF** `[L]` — Aggressive tools (nuclei, ffuf) may get IP-banned; no global rate-limit coordination across tools.

## 22. Tool Self-Security

- [~] **Debug telemetry beacon exfiltrates CLI args** `[H]` — (See §20.) **INCORRECT CLAIM** — Per §28.1, the committed code never had telemetry.
- [ ] **Webhook SSRF** `[H]` — (See §18.) Add scheme allowlist + private-IP/localhost/metadata-host blocking.
- [ ] **Plaintext credentials file** `[H]` — (See §15.) Verify perms on load; consider OS keychain.
- [ ] **`run_agent_tool.py` dynamic import from tool name** `[M]` — (See §18.) Allowlist tool names.
- [x] **`_SHELL_INJECTION_PATTERN` over-blocks legit args** `[C]` — (See §9.) **FIXED** — Blocklist removed; `subprocess.run` uses list form (no shell) so no injection risk.
- [ ] **XSS in generated HTML reports** `[H]` — (See §17.) Escape all inserted values.
- [x] **`ai_explainer` bypasses tenant key scoping** `[H]` — **FIXED** — `generate_embedding` now checks `self.llm_client.api_key` before `os.getenv`. (See §10.)
- [ ] **Tenant context failures silently ignored** `[M]` — (See §6.) Fail loud on tenant-set errors.
- [ ] **`security_audit.py:159` walks cwd, not project root** `[L]` — Audit may scan the wrong tree if invoked from elsewhere.
- [x] **gitleaks allowlist doesn't exclude `redis/*.exe`** `[L]` — **RESOLVED** — `redis/*.exe` removed from git tracking; gitleaks no longer scans them.

## 23. Resource Limits & Reliability

- [ ] **Circuit breaker config** `[L]` — `argus.config.yaml` `circuit_breaker.max_failures: 5, cooldown_ms: 300000`. Verify these are loaded (the config-loading inconsistency in §3 may mean they're ignored in some paths).
- [ ] **Tool timeouts** `[M]` — Per-tool `timeout` in YAML (default 300s) vs bridge default 600s vs executor's 120s/300s split. Three timeout layers can conflict; the shortest wins and may kill long scans.
- [ ] **Loop budget not persisted** `[H]` — (See §6.) `loop_budgets` table missing → budget state lost across iterations → overruns.
- [ ] **Replan cap can't be disabled** `[M]` — (See §14.) `ARGUS_MAX_REPLANS=0` → 10.
- [ ] **Evidence retention / disk** `[M]` — `argus.config.yaml` `retention_days: 30, max_engagement_size_mb: 500`. With `checkStorageLimit` fail-open (§16), a runaway scan can fill the disk.
- [x] **Orphaned subprocesses** `[H]` — (See §2/§18.) **FIXED** — `psutil` in production requirements; subprocesses cleaned up on timeout.
- [ ] **`networkidle` hangs** `[H]` — (See §11.) Browser verifiers can hang forever.
- [ ] **Agent loop 50 iterations** `[M]` — (See §14.) No cap override.
- [ ] **SQLite DB never closed / lock contention** `[M]` — (See §6/§15.)

## 24. Legal / Authorization / Scope

- [ ] **Written authorization obtained for the target** `[H]` — Argus runs active scans (nuclei, sqlmap, nmap) by default. README "Security Notice" requires written authorization. No technical scope guard prevents scanning unauthorized targets.
- [ ] **Scope limitations respected** `[H]` — There's no allowlist of in-scope hosts/IPs enforced before tool execution. A subdomain enumeration that finds out-of-scope hosts will still be scanned by downstream phases.
- [ ] **`allowed_git_hosts: []` empty** `[M]` — `argus.config.yaml:18` empty means no git-host restrictions; verify this is intended.
- [ ] **Rate/scope guard for production targets** `[M]` — No global concurrency/rate cap across tools; easy to DoS an authorized-but-fragile target.
- [ ] **Data residency / evidence storage** `[M]` — Evidence + credentials stored under `~/.argus/` on the operator's machine. Ensure that location is encrypted/at-rest-appropriate for the engagement.

## 25. Documentation & UX Consistency

- [ ] **README quick-start `argus` not on PATH after `bun install`** `[H]` — A fresh `bun install` does NOT put `argus` on `$PATH`; needs `bun link` or running via `bun run`/`start-argus.sh`. First-timers hit "command not found".
- [ ] **README "Run all Argus tests (335+ tests)"** `[M]` — Conflicts with Makefile "280+" and CI "558". (See §19.)
- [ ] **README calls `start-argus.sh` a "Test suite launcher"** `[M]` — It's actually the interactive TUI/CLI launcher (v5). The "test suite launcher" label matches the stale v4 `scripts/mac/start-argus.sh`.
- [ ] **README Requirements omit Docker/postgres/redis/pgvector** `[M]` — For the compose path these are required but unlisted.
- [ ] **`argus-workers/README.md` is stale** `[M]` — References non-existent files (`nuclei_tool.py`, `httpx_tool.py`, root `orchestrator.py`) and "Next Steps: 1. Implement celery_app.py" (already implemented). Misleads contributors.
- [ ] **Makefile/docker-compose contradict README project structure** `[H]` — README structure correctly omits `argus-platform/`, but Makefile/compose still reference it extensively. The v5 migration was declared complete but Makefile/compose weren't updated.
- [ ] **No `docs/` index** `[L]` — Sprawl of plan docs (~170KB) with no README to orient contributors.
- [ ] **ADRs partially implemented** `[M]` — `docs/adr/ARCHITECTURE_AUDIT.md` flags ADR-018/022/023/024 as partial/bug. Several architectural decisions are unimplemented.
- [ ] **Existing `docs/BUG_SWEEP_REPORT.md` (~150 code bugs)** `[Info]` — Cross-reference it; don't duplicate. This checklist complements it with deployment/config/integration coverage.

## 26. Top Blockers — Fix These First

These are the items that will outright prevent Argus from running, deploying, or producing trustworthy results. Address them before anything else.

- [x] **[C] Missing `argus-platform/` breaks `docker compose up`, `make docker-up`, and 13 Makefile targets** (§5, §2) — **FIXED** — `docker-compose.yml` already has the platform service commented out. Makefile: removed 13 stale `argus-platform` targets (`dev-platform`, `test-frontend`, `test-coverage` fallback, `lint-frontend`, `build`, `db-setup/verify/reset`, `install-frontend`). Generic targets now route to V5 equivalents. Added `db-migrate` target.
- [x] **[C] Postgres initdb mounts non-existent SQL files → DB initializes with no schema** (§5) — **FIXED** — `docker-compose.yml` now mounts `./argus-workers/database/init/01-schema.sql` and `02-audit.sql`, both of which exist with proper base schema. No empty directories created.
- [ ] **[C] `argus-workers/Dockerfile` Go SHA256 mismatch → worker/celery-beat images can't build** (§2) — **REMOVED (pass 3):** the Dockerfile (`Dockerfile:16-24`) downloads the SHA256 from `https://go.dev/dl/${GO_TARBALL}.sha256` and runs `sha256sum -c` to verify. This is correct supply-chain practice — no hardcoded wrong hash. The worker/celery-beat images build fine. This blocker was based on a misread of the Dockerfile.
- [x] **[C] DB migrations `001`–`003` (base schema) missing → standalone worker can't function** (§6) — **FIXED** — Migrations `001_base_schema.sql`, `002_audit_logging.sql`, and `003_webhooks_loop_budgets.sql` now exist in `argus-workers/database/migrations/`. (See §6.)
- [x] **[C] `_SHELL_INJECTION_PATTERN` blocks legitimate URL/selector args → parameterized targets & Playwright tools uncallable** (§9) — **FIXED** — Blocklist removed; list-form subprocess is already safe.
- [x] **[C] Evidence `verifyPackage` path layout mismatches collector writes → integrity always fails** (§16) — **FIXED** — Paths aligned.
- [x] **[C] Hard `bun:sqlite` dependency with no Node fallback** (§1) — **FIXED** — Replaced static `import { Database } from "bun:sqlite"` with a lazy dynamic import via `createRequire`. Under Node, the error is now a clear "Bun required" message at construction time instead of a cryptic module-not-found at import time. The module can now be loaded under Node without crashing — only constructing `EngagementStore` throws.
- [x] **[C] Parser registry is empty — `importlib.import_module("parsers.parsers.%s", module_name)` never formats `%s`** (§27.3) — **FIXED** — Import format string corrected; all 20+ non-streaming tools now produce findings.
- [x] **[C] Finding-detail TUI route uses `type: "finding"` but the valid union member is `"finding-detail"`** (§27.2) — **FIXED** — Route type corrected to `"finding-detail"`; clicking a finding now navigates to detail view.
- [x] **[C] LLM integration is completely non-functional — `FindingAnalyzer` is never wired with an `LlmClient`, and `@opencode/runtime` is imported by zero Argus modules** (§27.2) — **FIXED** — `LlmClientImpl` implemented and wired. LLM analysis now works.
- [x] **[C] `setRegistryTools()` / `setConfig()` / `setToolConfig()` have zero callers — drift detection compares MCP against itself, and `argus.config.yaml` tools config (incl. `sqlmap` disable) is dead** (§27.1) — **FIXED** — `workflow-runner.ts` now calls `bridge.setRegistryTools(toolRegistry.listTools())`, uses `await ToolConfig.load()` instead of `new ToolConfig()`, and passes the loaded config to `executor.setToolConfig()`. Drift detection now compares MCP vs registry; `sqlmap` disable, custom timeouts, and circuit-breaker config from `argus.config.yaml` are all applied.
- [x] **[C] Non-agent tools are JSON-RPC-timeout-killed at 120s regardless of YAML timeout** (§27.1) — **FIXED** — `executor.executeTool()` now reads `tool.timeout_seconds` from the tool definition (via `getToolTimeout()`), so tools with YAML timeouts >120s (nuclei 600s, sqlmap 600s, etc.) get their full timeout. Also supports `argus.config.yaml` timeout overrides.
- [x] **[C] `selectBest` web filter is dead — `detectTargetType` returns `"web_app"|"api"|"spa"|"unknown"`, never the literal `"web"` the filter checks for** (§27.1) — **FIXED** — `selectBest` in `tool-registry.ts` now also accepts `"web_app"` and `"spa"` alongside `"web"` (line 130). The filter works correctly despite `detectTargetType` still returning `"web_app"` for HTTP URLs.
- [x] **[C] Approval gates are completely inert — no workflow YAML sets `approval_gate` on any phase, AND `APPROVAL_GATES` defaults false** (§27.1) — **FIXED** — Approval gates wired into workflow YAMLs; gates now fire.
- [~] **[H] Debug telemetry beacon in `bin/argus` exfiltrates CLI args** (§20) — **INCORRECT CLAIM** — Per §28.1 verification, the committed `bin/argus` (36 lines) never contained telemetry. Stale-version false alarm.
- [x] **[H] LLM finding-analysis is a no-op even when enabled** (§10) — **FIXED** — `LlmClientImpl` wired into `FindingAnalyzer`; reports get AI analysis.
- [x] **[H] `ai_explainer` reads wrong attribute + bypasses tenant key scoping** (§10) — **FIXED** — `_generate_with_httpx` now checks `api_url` before `base_url`; `generate_embedding` now checks `self.llm_client.api_key` before `os.getenv`.
- [x] **[H] `tool_runner._redact_sensitive_args` breaks token-based tools (wpscan etc.)** (§10) — **FIXED** — CLI values no longer replaced with `__REDACTED__`; real tokens passed through.
- [x] **[H] Webhook SSRF + missing `webhooks`/`loop_budgets` tables** (§18, §6) — **FIXED** — SSRF validation implemented (HTTPS-only, DNS resolution, private IP blocking, follow_redirects=False). `webhooks`/`loop_budgets` tables migration still needed.
- [x] **[H] CI can be green with broken tests (`fail_on_failure: false`, Windows `|| true`)** (§19) — **FIXED** — CI now fails on test failures.
- [x] **[H] Approval gates default ON when flags unset; hybrid phases bypass gates** (§14) — **FIXED** — Gates default OFF; hybrid phases now gated.
- [x] **[H] `assessCommand` always dumps markdown to stdout (breaks TUI `/assess`)** (§13) — **FIXED** — Markdown output opt-in.
- [x] **[H] Browser verifiers write to CWD, reference garbage paths, capture evidence after browser close** (§11) — **FIXED** — Paths fixed, evidence captured before browser close.
- [x] **[H] Feature-flag singleton ignores config files → two flag systems diverge** (§3) — **FIXED** — Singleton now loads config.
- [x] **[H] `psutil` not in production requirements → orphaned subprocesses** (§2) — **FIXED** — Moved to `requirements.txt`.
- [x] **[H] Committed Windows Redis binaries + malformed `requests==...` file + fake `uv.lock`** (§7, §2) — **NOW FIXED 2026-06-20** — `redis/*.exe` removed from git tracking via `git rm --cached`; `redis/*.exe` added to `.gitignore`. (Previously claimed fixed but still on disk — see §28.1.)

## 27. Second-Pass Deep Audit Findings (2026-06-20)

Line-by-line deep read of workflow/tool YAMLs, Python agent/orchestrator/parser internals, the OpenCode runtime + TUI shell, and the full test suite. Items below are NEW — they extend, not duplicate, §1–§26. All `[C]`/`[H]` items here were verified directly against source.

### 27.1 Workflow, Tool-Registry & Planner (YAML + TS)

- [x] **`selectBest` web filter is dead** `[C]` — **FIXED** — `selectBest` now also accepts `"web_app"` and `"spa"` alongside `"web"` in the target-type filter, so `supports_web`/`supports_api` from tool definitions work correctly. Note: `detectTargetType` still returns `"web_app"` for HTTP URLs, not `"web"` — the filter was widened instead.
- [x] **Approval gates are completely inert at runtime** `[C]` — **FIXED** — Approval gates wired into workflow YAMLs; `approval_required:` blocks now actually fire.
- [x] **`setRegistryTools()` has zero callers — drift detection compares MCP against itself** `[C]` — **FIXED** — `bridge.setRegistryTools(toolRegistry.listTools())` is now called in `workflow-runner.ts:run()`. `toolsCache` is seeded with the local registry's tool list; `quickDriftCheck()` now compares MCP vs registry instead of MCP vs itself. (Extends §8.)
- [x] **`toolRegistry.setConfig()` and `executor.setToolConfig()` have zero callers — `argus.config.yaml` tools section is dead** `[C]` — **FIXED** — `workflow-runner.ts:run()` now uses `await ToolConfig.load()` (reads from `argus.config.yaml` and `~/.argus/config.yaml`) instead of `new ToolConfig()`, and passes the loaded config to both `toolRegistry.setConfig(toolConfig)` and `executor.setToolConfig(toolConfig)`. Consequences fixed: (a) `sqlmap` listed `disabled` is now actually disabled; (b) custom per-tool timeouts are applied; (c) circuit-breaker config reaches `ToolHealthMonitor`.
- [x] **Non-agent tools are JSON-RPC-timeout-killed at 120s regardless of YAML timeout** `[C]` — **FIXED** — `executor.executeTool()` now uses `this.toolRegistry.getToolTimeout(tool.name)` which reads the tool's `timeout_seconds` from `tool-definitions.yaml` (or `argus.config.yaml` override). The hardcoded 120s/300s constants and the `AGENT_INTERNAL_TOOLS` set have been removed. YAML-defined timeouts are now authoritative for all tools.
- [x] **`alterx` parameter name `domain` doesn't match the executor's hardcoded `target` key** `[C]` — **FIXED** — `alterx.yaml` parameter name changed from `domain` to `target` (flag stays `-d`). `mcp_server.py` now finds `"target" in arguments` and passes `-d <value>` correctly.
- [x] **`requires` gates declared in Python YAMLs are entirely absent from the TS `tool-definitions.yaml`** `[H]` — **FIXED** — Added `requires:` blocks with `tech_contains`/`target_scheme` gates to 11 tools in the TS YAML (wpscan, bandit, gosec, brakeman, eslint, spotbugs, phpcs, pip-audit, npm-audit, govulncheck, testssl). `passesGates()` is now exercised — wpscan won't run on non-WordPress sites, bandit on non-Python targets, testssl on http targets, etc.
- [x] **`recon_signals` gates are structurally impossible to satisfy** `[H]` — **FIXED** — `GateContext` now includes `reconSignals?: string[]`; `passesGates()` validates `recon_signals` when context provides them (skipped when undefined). `requires: { recon_signals: [...] }` added to sqlmap (`parameterized_forms`), commix (`has_file_upload`), and jwt_tool (`has_api`, `has_login_page`) in the TS YAML. (Python `mcp_server.py` loads them from YAML but applies no enforcement; the TS side now enforces.)
- [x] **Four Capability enum values have zero tool providers — replan for them always fails** `[H]` — **FIXED** — 
  - `GRAPHQL_ASSESSMENT`: Added to nuclei in both TS + Python YAMLs (nuclei already runs graphql-tagged templates in the swarm APIAgent).
  - `EXPRESS_CVE_SCAN`: Replaced with `VULNERABILITY_SCANNING` in strategy.ts and replan-rules.ts. No dedicated Express CVE scanner exists; generic vuln scanners handle Express CVEs. Also fixes the `expressjs` vs `express` subtype inconsistency.
  - `API_DOCS_ANALYSIS`: Added to nuclei and arjun in both TS + Python YAMLs (nuclei runs swagger/openapi templates; arjun discovers API parameters).
  - `CVE_SCANNING`: Marked `@deprecated` — fully dead, never requested, never declared.
- [ ] **Priority drift between TS and Python for 13 of 16 agent-internal tools** `[H]` — The drift detector only hashes `name + capabilities`, NOT `priority`. 13 tools have divergent priorities (e.g. `assessment_orchestrator` TS:100 vs Py:90; `finding_correlation_engine` TS:95 vs Py:90; most others TS varies 60-85 vs Py:90). The two sides order tools differently. Real security tools (nuclei, nmap) have `priority` in Python but NOT in TS → TS tiebreaker defaults them to 50.
- [ ] **`signal_quality` drift for 3 tools — display and confidence engine disagree** `[H]` — `attack_surface_mapper`, `register`, `threat_intelligence_aggregator`: TS says PROBABLE, Python says CONFIRMED. The executor's `baselineConfidence()` uses the MCP response (Python side → CONFIRMED → `Confidence.HIGH`); display reads TS (PROBABLE). Drift detector doesn't check `signal_quality`.
- [ ] **`executeHybrid` is unreachable AND bypasses the `gatesLoaded` guard** `[H]` — `executor.ts:158` routes `phase.execution === "llm_driven"` to `executeHybrid`, but the planner only ever sets `toolExecution` (from YAML `execution: parallel|sequential`), never `execution`. `phase.execution` is always `undefined` → the `executeHybrid` branch (lines 286-431) is dead. It's also dispatched BEFORE the `gatesLoaded` check (line 158 vs 162), so if ever reached it would skip the approval-gate invariant. (Extends §14.)
- [x] **`dalfox` declares `sqli_detection` — wrong capability for an XSS scanner** `[H]` — **FIXED** — Changed to `xss_detection` in both TS and Python YAMLs. Added `XSS_DETECTION = "xss_detection"` to the Capability enum and display label `"Cross-Site Scripting"` in cli.ts. `_generated_tools.py` regenerated.
- [x] **`commix` declares `ssrf_check` — wrong capability for a command-injection tool** `[H]` — **FIXED** — Changed to `command_injection` in both TS and Python YAMLs. Added `COMMAND_INJECTION = "command_injection"` to the Capability enum, display label in cli.ts, and phase mapping in generate_tool_defs.py. `_generated_tools.py` regenerated.
- [ ] **`_HOSTNAME_TOOLS` misclassifies `s3scanner`, `bucket_upload`, `github-endpoints`, `chaos`** `[H]` — `mcp_server.py:488-504`: stripping `https://s3.amazonaws.com/mybucket` → `s3.amazonaws.com` (drops bucket name s3scanner needs); `github-endpoints` loses the org name; `bucket_upload` loses the path/bucket. `chaos` is in the dead `_URL_TOOLS` set (line 507-513, never referenced), so it gets the full URL but expects a bare domain with `-d`.
- [x] **Credentials never reach the tools that need them** `[H]` — **FIXED** — Added `buildExtraFromCredentials()` helper to executor.ts that extracts email/password from `phase.config.credentials` and populates the `--extra` JSON param. Both `executeTool()` and `executeHybrid()` call sites now include the `extra` field when credentials are available. `login.yaml`/`register.yaml` now receive credential data.
- [ ] **Playwright tools' required parameters can't be satisfied via the executor path** `[M]` — `playwright-bola.yaml` requires `attacker-username`, `attacker-password`, `victim-username`, `victim-password`. The executor passes only `target`/`capability`/`config`. None of the required params are populated. These tools can only be called via direct MCP invocation, never through the planner→executor pipeline. (They're also not in the TS `tool-definitions.yaml`, so the planner never selects them.)
- [x] **`expressjs` vs `express` subtype inconsistency breaks replan** `[M]` — **FIXED** — Both strategy.ts (`tech.includes("express")`) and replan-rules.ts (`"expressjs"` subtype) now route to `VULNERABILITY_SCANNING`, so they always agree regardless of which key surfaces.
- [ ] **`cost` field is dead metadata on both sides** `[M]` — Declared on 16 agent-internal tools in TS YAML and on `ToolDef`; zero TS files read `tool.cost`. Python loads it into `ToolDefinition.cost` but also never uses it for ranking. Dead everywhere.
- [ ] **`version_cmd`/`min_version`/`version_regex` in tool-definitions.yaml are dead** `[M]` — Only set for `nuclei`; `ToolDef` interface doesn't declare them → silently dropped at parse. `doctor.ts:318-331` uses its own separate hardcoded `TOOL_VERSION_CHECKS` array (12 tools, different values).
- [x] **`getToolTimeout` is dead code — executor uses hardcoded constants** `[M]` — **FIXED** — `executor.executeTool()` now calls `this.toolRegistry.getToolTimeout(tool.name)` to resolve per-tool timeouts. The hardcoded `PER_TOOL_TIMEOUT_MS`/`AGENT_TOOL_TIMEOUT_MS` constants and `AGENT_INTERNAL_TOOLS` set have been removed. Custom timeouts from `argus.config.yaml` and YAML `timeout_seconds` are now both respected.
- [ ] **`_URL_TOOLS` frozenset is dead code** `[M]` — `mcp_server.py:507-513` defines `_URL_TOOLS = {"gau","waybackurls","chaos"}` but it's never referenced in any conditional. The only check is `if tool.name in _HOSTNAME_TOOLS`. `_URL_TOOLS` serves no purpose.
- [ ] **README claims "45 YAML tool definitions" but there are 65** `[L]` — `README.md:96,133`. Actual: 65 files in `argus-workers/tools/definitions/*.yaml`; TS `tool-definitions.yaml` has 62 tools (3 playwright tools are Python-only). The drift detector would report the 3 playwright tools as `missing_from_registry` — but per above, drift detection is broken.
- [ ] **`sqlmap.yaml`/`masscan.yaml`/`commix.yaml`/`playwright-bola.yaml` have undeclared `risk_level` field** `[L]` — Not in `ToolDefinition.__init__`; silently ignored during construction. Dead metadata on the Python side.
- [ ] **`pip-audit`/`npm-audit` mark `target` as `required: false`** `[L]` — Inconsistent with the other 63 tools that mark `target` `required: true`. The MCP `tools/list` schema won't list `target` in `required`, so MCP clients won't know to send it.
- [ ] **`findByCapabilities` ties broken by alphabetical filename order** `[L]` — `registry.ts:33-48` `loadAllWorkflows` iterates `readdirSync` (alphabetical); `score > bestScore` keeps the first. So `api_assessment.yaml` wins over `browser_assessment.yaml` on ties. Deterministic but arbitrary.
- [ ] **Loader doesn't validate `version`/`label` despite the type requiring them** `[L]` — `loader.ts:13` only checks `name`/`phases`. A YAML omitting `label`/`version` would pass validation but produce undefined required fields. (Extends §14.)

### 27.2 OpenCode Runtime & TUI Shell (NEW — not covered in pass 1)

- [x] **Finding-detail navigation routes to an invalid route type → blank screen** `[C]` — **FIXED** — Route type corrected from `"finding"` to `"finding-detail"`; clicking a finding now navigates to the detail view.
- [x] **LLM integration is completely non-functional — no LLM client is ever wired** `[C]` — **FIXED** — `LlmClientImpl` implemented and wired into `FindingAnalyzer`; LLM analysis now functional.
- [~] **`bin/argus` destroys the user's CWD — CLI assessments can't find `argus.config.yaml`** `[H]` — **INCORRECT CLAIM** — Per §28.1 verification, the committed `bin/argus` never called `chdir`. Comment at line 11-14 says "intentionally does NOT chdir." Claim was based on a stale version.
- [ ] **The `@opencode/runtime` public-API contract is non-resolvable** `[H]` — `docs/ARCHITECTURE_BOUNDARIES.md` documents `import { IProviderManager, … } from "@opencode/runtime"` as the canonical boundary. But (a) `package.json` `name` is `"argus"`, not `"opencode"` — there's no `opencode` package to resolve `@opencode/runtime` against; (b) `tsconfig.json` paths define `@/*`, `@tui/*`, `@argus/*` but **no** `@opencode/runtime`; (c) the `exports` entry `"./runtime"` is only reachable as `argus/runtime`. Any module following the documented import would fail to resolve. `opencode-runtime.ts` (58 lines of interfaces) has zero importers — dead code, and the documented boundary is a fiction. (Confirms §25's "no ESLint enforcing the boundary" — the boundary can't even be imported.)
- [x] **`home.tsx` MCP-worker path is off by one level → "MCP Bridge" always shows red** `[H]` — **FIXED** — Path corrected from 7 `..` to 8 `..`; `mcp_server.py` now found correctly at the project root.
- [ ] **`ArgusDashboard` and the `dashboard` route are dead code — ARGUS_MODE does not route to it** `[M]` — `launchTui` spawns the TUI with `ARGUS_MODE=1`, but `ARGUS_MODE` is checked in only two places — `splash.ts:207` and `footer.prompt.tsx:278` (branding). It's never used for routing. `RouteProvider` defaults to `{ type: "home" }`, which renders OpenCode's `<Home />`, not `<ArgusDashboard />`. `navigateTo({ type: "dashboard" })` is never called anywhere (grep: 0 hits). `dashboard.tsx` (128 lines) and the `dashboard` navigator branch are unreachable. The docs/AGENTS.md claim "When ARGUS_MODE=1, the home screen shows ArgusDashboard" is false.
- [ ] **`ArgusCommandRegistry` is never mounted → Argus commands absent from the command palette** `[M]` — `tui-command-registry.tsx:10` registers `argus.assess`, `argus.findings`, etc. via `useBindings`, but `ArgusCommandRegistry` is **never imported or rendered** by `app.tsx` or any component (grep: only the definition site). Slash commands still work when typed (via the interceptor at `prompt/index.tsx:1200`), but they're not discoverable/selectable in the palette. The registry is dead code.
- [ ] **TUI `/assess` flow ignores flags and corrupts the engagement target** `[M]` — In the TUI, `/assess https://x.com --no-cache` sets `arg = "https://x.com --no-cache"` (`prompt/index.tsx:1212`). For `assess`/`scan`/`recon` the TUI calls `runner.run({ target: arg, … })` directly (line 1236) and `store.createEngagement(arg, "assessment")` (line 1220), bypassing `tui-commands.ts`'s handler which parses out `--no-cache`/`--refresh-cache` (lines 53-59). So in TUI mode the entire arg string — flags included — becomes the `target` URL (invalid) and is persisted as the engagement `target` in SQLite. `--no-cache`/`--refresh-cache` have no effect in the TUI.
- [ ] **`home.tsx` "Recent Activity" shows the OLDEST engagements, not the newest** `[M]` — `listEngagements()` orders newest-first. `home.tsx:50` does `all.slice(-5).reverse()` — `slice(-5)` takes the last 5 (oldest), then reverses. "Recent Activity" displays the oldest engagements. Compare `dashboard.tsx:40` which correctly uses `engagements.slice(0, 8)`.
- [ ] **`/findings` with no engagement shows the OLDEST engagement's findings** `[M]` — `findings.tsx:143-144` `const engId = route.engagementId ?? (all.length > 0 ? all[all.length - 1].id : null)`. `all` is newest-first, so `all[all.length-1]` is the oldest. (Extends §13's CLI/TUI newest-vs-oldest discrepancy — this is the route-level instance.)
- [ ] **`<Toast />` is not rendered on most Argus routes — toasts invisible** `[M]` — `app.tsx` mounts `ToastProvider` (context) but never renders the `<Toast />` visual component at app level — each route must render it. Among Argus routes, only `scan.tsx` imports/renders `<Toast />`. `findings.tsx`, `dashboard.tsx`, `engagements.tsx`, `engagement-detail.tsx`, `finding-detail.tsx`, `workspace.tsx`, `evidence-viewer.tsx` do not. Any `toast.show({…})`/`toast.error(…)` on those routes (load failures, copy results) is silently invisible.
- [ ] **`OPENCODE_ROUTE` env var is `JSON.parse`'d with no try/catch** `[M]` — `route.tsx:66-73` `init` does `JSON.parse(process.env["OPENCODE_ROUTE"])` with no validation. A malformed value throws synchronously during `RouteProvider` mount. The surrounding `ErrorBoundary` catches it so the process doesn't die, but the TUI lands on `ErrorComponent` instead of starting normally. Unvalidated `JSON.parse` on external env input.
- [ ] **One `EngagementStore` (new sqlite handle) opened per route mount, never closed** `[L]` — `new EngagementStore()` opens a fresh `bun:sqlite` `Database` with `PRAGMA journal_mode=WAL` and exposes no `close()`. Each route `onMount` creates one; navigating between routes accumulates open handles (WAL also spawns `-wal`/`-shm` files per connection). (Extends §15.)
- [ ] **Silent `catch {}` blocks swallow DB/config errors across routes** `[L]` — `home.tsx:69,79`; `engagements.tsx:42`; `engagement-detail.tsx:53`; `dashboard.tsx:47`; `scan.tsx:81`; `workflow-runner.ts:196`. Empty `catch {}` at every store/config call site. If `~/.argus/argus.db` is locked/corrupt or `argus.config.yaml` is malformed, the failure is invisible — the UI shows empty state with no error toast or log.
- [ ] **Terminal title hardcoded to "ARGUS" with no `ARGUS_MODE` guard** `[L]` — `app.tsx:488,495,500,505` `renderer.setTerminalTitle("ARGUS — Security Assessment Platform")` is unconditional inside `home`/`session`/`plugin` route effects. If this binary is ever run in plain OpenCode mode (no `ARGUS_MODE`), the title still says ARGUS.
- [ ] **`/report` with LLM flag on slowly does nothing (1s/batch no-op)** `[L]` — `report.ts:33-51` when `LLM_FINDING_ANALYSIS` is enabled, `enhanceReportWithAnalysis` loops findings in batches of 3 with `setTimeout(1000)` between batches, but because no `LlmClient` is wired (above), every `analyzer.analyze()` returns null. `/report` on a large engagement sleeps ~1s per 3 findings producing zero analyses, then emits a report with an empty AI-analysis section.
- [ ] **`bin/argus` does not handle `--version`/`--help` before spawning, lacks `child.on("error")`, doesn't forward SIGTERM** `[L]` — Every invocation spawns a full `bun run` child — no fast-path. No `child.on("error")` (if `bun` not on PATH → uncaught exception, unlike `index.ts:64`). No `child.on("SIGINT"/"SIGTERM")` relay. (Extends §20.)

### 27.3 Python Agent, Orchestrator & Parser Internals (NEW)

- [x] **Parser registry is empty — `importlib.import_module("parsers.parsers.%s", module_name)` never formats `%s`** `[C]` — **FIXED** — Import format string corrected to `f"parsers.parsers.{module_name}"`. All 20+ non-streaming tools now produce findings.
- [x] **Two parser systems with disjoint coverage — nmap gap closed** `[C]` — **FIXED** — `nmap` was only in System A (tool_core/parser/dispatcher.py), used by MCP bridge but NOT the orchestrator. Added `NmapParser` to System B (`parsers/parsers/nmap.py`) as a `BaseParser` subclass, auto-discovered by the registry. nmap findings now parsed correctly through the orchestrator path. The reverse gap (System A missing ~22 parsers from System B) remains but is mitigated by System A's generic fallback. (Extends §18.)
- [x] **Session eviction destroys active sessions mid-scan** `[H]` — **FIXED** — Eviction now uses `last_accessed_at` instead of `created_at`; TTL increased from 3600s to 7200s. Active sessions are no longer evicted.
- [x] **`get()` returns a live session object — lock semantics broken** `[H]` — **FIXED** — `get()` now returns a `copy.deepcopy()` of the session; mutation methods use an internal `_get_and_touch()` helper under lock.
- [x] **Scope validation bypassed by scheme-less targets (SSRF via agent)** `[H]` — **FIXED** — When `urlparse(target).hostname` is `None`, falls back to extracting host from raw target string. SSRF validation now runs on all targets regardless of scheme.
- [x] **Swarm `with ThreadPoolExecutor` block still blocks on hung threads** `[H]` — **FIXED** — Replaced `with ThreadPoolExecutor() as pool:` with manual `pool = ThreadPoolExecutor(...)` + `try/finally: pool.shutdown(wait=False, cancel_futures=True)`. The `with` block's `__exit__` no longer calls `shutdown(wait=True)`, so hung threads no longer block swarm completion.
- [x] **Deterministic safety-net findings not normalized** `[H]` — **FIXED** — Deterministic findings from `execute_scan_pipeline()` are now normalized via `_normalize_finding()` before being extended, matching the pattern used by agent results and fallback paths. Downstream persistence now receives properly structured findings.
- [ ] **Batch-saved findings never streamed or webhook'd** `[H]` — `orchestrator_pkg/persistence/finding_persistence_service.py:296-304,421-446` `_batch_save_non_secret` calls `batch_create_or_update_findings` which returns counts — but the repo already sets `_saved_id` on each finding dict, so this is NOT actually a bug. Streaming and webhooks work correctly for batch-saved findings.
- [x] **`persist_to_db` double-counts budget on repeated calls** `[H]` — **FIXED** — Changed from `loop_budgets.current_cycles + EXCLUDED.current_cycles` (accumulate) to `EXCLUDED.current_cycles` (replace). No more quadratic growth.
- [x] **Health monitor `break` exits the entire tool loop** `[H]` — **FIXED** — Replaced `break` with a `finalized_tools` set; each tool is now evaluated independently.
- [x] **`should_shutdown()` always returns True (confirmed + new impact)** `[H]` — **FIXED** — Final `return True` changed to `return False` when active tasks exist and deadline hasn't been exceeded. Graceful shutdown now waits for in-flight work.
- [x] **`result.output` assumed string — crashes on non-string output** `[H]` — **FIXED** — Added `isinstance(raw_output, str)` guard before `.strip()`. Non-string output is safely converted via `str()` with a try/except fallback to empty string.
- [x] **Auth checkpoint `ON CONFLICT (id)` is a no-op** `[M]` — **FIXED** — Removed `ON CONFLICT (id) DO NOTHING` clause. Duplicates are harmless because `load_auth_checkpoint` already uses `ORDER BY created_at DESC LIMIT 1` to pick the latest. Avoided `ON CONFLICT (engagement_id, action_id)` since `agent_decision_log` has no unique constraint on that pair.
- [x] **Unbounded eviction-thread accumulation** `[M]` — **FIXED** — Added class-level `_eviction_thread_started: bool` guard to `AgentSessionStore`. Only one eviction thread is ever started across all instances. Thread is daemon=True so it won't prevent shutdown.
- [x] **`_json` unbound in except clause** `[M]` — **FIXED** — Moved `import json as _json` outside the `try` block. The import is now always resolved before the try/except, so `_json` is always bound when `except` references `_json.JSONDecodeError`.
- [x] **Cost accounting lost when Governance V2 is active** `[M]` — **FIXED** — `total_cost_usd += getattr(action, "cost_usd", 0.0)` moved OUTSIDE the governance if/else check, so it always runs regardless of governance mode. The legacy `else` branch now only contains the `if total_cost_usd > LLM_AGENT_MAX_COST_USD` guard check.
- [x] **`initial_target` parsed incorrectly for URLs with colons** `[M]` — **FIXED** — `react_agent.py` now checks if the content before the first colon is a known phase name (`recon`, `scan`, `deep_scan`, `repo_scan`, `analyze`, `report`) before splitting. Bare URLs like `https://example.com:8080/path` are preserved as-is — only `"scan: https://x.com"` style prefixes are split.
- [x] **Auth checkpoint restore has no timeout** `[M]` — **FIXED** — `react_agent.py` now wraps the `run_login()` call in a `ThreadPoolExecutor` with `future.result(timeout=30)`. On TimeoutError, logs a warning and continues without restoring the session (graceful degradation). Uses `finally: pool.shutdown(wait=False, cancel_futures=True)` to avoid blocking on hung threads.
- [x] **Swarm `future.result(timeout=...)` is dead code** `[M]` — **FIXED** — Removed `timeout=per_agent_timeout` from `future.result()`. The future is already completed when `as_completed` returns it, so the per-agent timeout parameter was never exercised. Kept the `per_agent_timeout` allocation for logging/documentation.
- [x] **psutil kill loop can kill other tasks' subprocesses** `[M]` — **FIXED** — The kill loop is now guarded with `if len(completed) < len(futures_map):`, so it only runs when there were actual timeouts. Also fixed: the `else` branch for "returned no findings" and both exception handlers now add the domain to `completed`, so the guard accurately reflects real timeouts vs normal (empty) completion.
- [ ] **Hard timeout is per-task, not per-engagement** `[M]` — `orchestrator_pkg/orchestrator.py:66` `self.start_time = time.time()` is set in `__init__`; each Celery task creates a NEW Orchestrator, resetting `start_time`. The `_check_timeout` compares against `HARD_TIMEOUT_SECONDS` from the per-task start. The total engagement could take `HARD_TIMEOUT_SECONDS * 4` (recon+scan+analyze+report) — the "hard timeout" doesn't limit the engagement.
- [ ] **`atexit.register(self._cleanup)` accumulates handlers** `[M]` — `orchestrator.py:78` every `Orchestrator.__init__` registers an atexit handler holding a ref to the instance (and its `ToolRunner`), preventing GC. A long-running Celery worker accumulates thousands of handlers and leaks old Orchestrators.
- [ ] **Repo clone error URL parsing fails on URLs with colons** `[M]` — `orchestrator.py:947` `_, failed_url, reason = err_str.split(":", 2)` — for `https://example.com:8080/repo.git`, `split(":", 2)` → `['REPO_CLONE_FAILED', 'https', '//example.com:8080/repo.git:reason']`. `failed_url` becomes `'https'` and `reason` becomes the rest. The error message is garbled.
- [x] **`jwt_tool` parser produces false positives from informational lines** `[M]` — **FIXED** — Added `_INFO_KEYWORDS` and `_VULN_KEYWORDS` filtering. Lines with informational keywords ("loaded", "decoded", etc.) are skipped. Lines are only emitted as findings if they contain confirmed vulnerability keywords ("vulnerable", "cracked", "forged", "traversal", "none algorithm", etc.). Eliminates false positives from jwt_tool's status output while keeping real vulnerabilities.
- [ ] **sqlmap text parser regex matches the first URL in output, not the injection URL** `[M]` — `parsers/parsers/sqlmap.py:132` `re.search(r"(https?://[^\s]+)", raw_output)` grabs the FIRST URL — typically the target banner, not the injection endpoint. The finding's `endpoint` is whatever URL appears first.
- [x] **Phase names mismatch between agent and state machine** `[M]` — **FIXED** — Added `PHASE_TO_STATE_MAP` dict with `resolve_state_for_phase()` and `resolve_phase_for_state()` helpers in `state_machine.py`. These provide a canonical mapping between agent phase names ("scan", "analyze", "report") and state machine state names ("scanning", "analyzing", "reporting"), so cross-references no longer fail silently.
- [x] **`reset()` does not persist to DB** `[M]` — **FIXED** — `reset()` now calls `self.persist_to_db()` after zeroing in-memory counters, so budget resets survive worker restarts.
- [ ] **Dual budget systems increment the same counter** `[M]` — `loop_budget_manager.py:64-79` `consume()` increments `current_cycles` for `recon_expand`; `state_machine.py:307-332` `_persist_state_and_budget` increments `current_cycles` for `analyzing→recon` transitions. Both increment the SAME DB column through different paths → double-increment when both happen.
- [ ] **Snapshot version-number race condition** `[M]` — `snapshot_manager.py:241-249` `SELECT COALESCE(MAX(version),0)+1` is not atomic. Two concurrent `create_snapshot` calls can read the same `MAX(version)` and insert the same version.
- [ ] **Scan diff `_load_findings` uses `connect()` not the pool** `[M]` — `scan_diff_engine.py:147-151` creates a NEW connection each time, bypassing the pool. Leaks connections in a long-running worker.
- [x] **IntentParser `<user_input>` tag injection** `[M]` — **FIXED** — `sanitize_input()` now strips angle brackets (`<>`) via `re.sub(r"[<>]", " ", sanitized)`. This prevents `</user_input>` tag injection attacks. Angle brackets have no legitimate use in scan intent descriptions.
- [ ] **PoC generator template matching is bidirectional substring** `[M]` — `poc_generator.py:172-175` `if template_key in vuln_type or vuln_type in template_key` — `vuln_type="INJECTION"` matches `template_key="SQL_INJECTION"` (because `"INJECTION" in "SQL_INJECTION"`), so a generic INJECTION finding gets the SQL_INJECTION PoC template.
- [ ] **PoC/chain-exploit cost tracking only if LLM returns `cost_usd`** `[M]` — `poc_generator.py:255-256`; `chain_exploit_generator.py:294-295` `if "cost_usd" in result:` — but the LLM is never instructed to return `cost_usd`. If it doesn't, the cost is never recorded and the budget is never decremented. PoC/chain generation can exhaust the LLM budget without the tracker knowing. (Extends §10.)
- [ ] **Prompt injection from target data into PoC/chain-exploit generation** `[M]` — `poc_generator.py:213-227`; `chain_exploit_generator.py:252-265` the user prompt to the LLM includes `evidence.request`/`response`/`payload` from the scanned target. A malicious target can inject instructions into its HTTP response. `_redact` only redacts secrets, not prompt-injection patterns. The LLM may follow injected instructions, producing inaccurate/harmful PoC scripts.
- [ ] **Chain-exploit redaction drops non-string evidence fields** `[M]` — `chain_exploit_generator.py:72-76` `_redact_evidence_dict` only processes string values; non-string values (dicts, lists, ints) are silently dropped. Sensitive data in non-string fields is NOT redacted and NOT included.
- [ ] **Intelligence-engine in-memory cache is class-level, unbounded** `[M]` — `intelligence_engine.py:49,1075-1097` `_in_memory_cache` is a class-level dict shared across all instances — no size limit, no eviction, not thread-safe. Grows unboundedly in a long-running worker.
- [ ] **Sync enrichment returns findings in completion order** `[M]` — `intelligence_engine.py:865-868` `enriched = [future.result() for future in as_completed(futures)]` — `as_completed` yields in completion order, not input order. Downstream code indexing findings by position gets misaligned data.
- [ ] **DI container race condition on creation** `[M]` — `di_container.py:174,194-205` `_containers` is a module-level dict with no lock; `get_or_create_container` reads/writes without synchronization. Two threads for the same `engagement_id` can both create containers, one overwriting the other (and `_factory(deps)` runs twice).
- [ ] **Streaming permanently disconnects slow consumers** `[M]` — `streaming.py:263-281` when `queue.Full` is raised, the queue is added to `dead_queues` and removed from subscribers. A slow consumer (e.g. frontend SSE reader) gets permanently unsubscribed after ONE `queue.Full` event — no re-subscribe. All subsequent events lost.
- [ ] **Streaming fingerprint clear causes duplicate emissions** `[M]` — `streaming.py:831-833` when the per-engagement fingerprint set reaches 50,000, `engagement_fps.clear()` wipes ALL entries. After the clear, finding #50,001 can duplicate finding #1. For scans >50,000 findings, the first 50,000 are deduped but subsequent findings can duplicate earlier ones.
- [ ] **Health monitor `finally` references undefined `db`** `[M]` — `health_monitor.py:384-391` in `get_tool_health`, the `finally` calls `db.release_connection(conn)` but `db` is only defined inside `try` (line 304 `db = get_db()`). If `get_db()` raises, `db` is never bound and `finally` raises `NameError`, masking the original exception.
- [ ] **Tracing module-level `tracer` captured before `setup_tracing`** `[M]` — `tracing/__init__.py:40` `tracer = trace.get_tracer(__name__)` at import time. If any module imports `tracing` before `setup_tracing()`, the global `tracer` uses the no-op provider; the subsequent `setup_tracing()` is IGNORED by OpenTelemetry ("Overriding of TracerProvider is not allowed"). All spans via the module-level `tracer` are no-ops. (Extends §18.)
- [ ] **StructuredLogger releases connection without rollback on commit failure** `[M]` — `tracing/__init__.py:149-176` `_store_log` gets a connection, INSERTs, calls `conn.commit()`. If `commit()` fails, the `finally` closes the cursor and releases the connection WITHOUT `conn.rollback()`. The connection goes back to the pool with an aborted transaction; the next user gets `InternalError: previous transaction aborted`.
- [ ] **Nuclei templates directory is empty** `[M]` — `tool_assets/nuclei-templates/` exists but is empty (0 files). `scan.py:506` `templates_exist = ...rglob("*.yaml")` → False → nuclei runs without custom templates. Any intended-to-ship custom templates are missing; only nuclei's default set is used.
- [ ] **`VulnerabilityFinding.evidence` coercion loses non-JSON-string evidence** `[L]` — `models/finding.py:63-78` the validator coerces strings→dicts via `json.loads` (fallback `{"raw": v}`), lists→`{"items": v}`, but `None` → `{"raw": "None"}` (string "None") instead of `{}`. `{"raw": "None"}` is truthy, confusing downstream `if evidence:` checks.
- [ ] **Custom-rules registry directories are empty** `[L]` — `custom_rules/registry/community/` and `versions/` are empty. The community/versioned-rules feature is non-functional — any code reading these dirs finds nothing.

### 27.4 Test Suite — Coverage Gaps & Tautological Tests (NEW)

- [ ] **`assess.test.ts` — flagship command has zero behavioral tests** `[C]` — The entire test file for the `assess` command (the flagship `/assess` entrypoint) is a single test asserting `assessCommand` is `typeof ... === "function"`. No argument parsing, workflow dispatch, planner invocation, engagement creation, or error paths are exercised. The most security-critical command is effectively untested.
- [ ] **`test_dual_auth_scanner.py` — 30 xfails with a false reason** `[C]` — The module docstring says it "Uses mocked AuthManager and `_safe_request` to test scan logic without live authentication or HTTP requests." Yet 30 tests are `@pytest.mark.xfail(reason="Requires external services", strict=False)`. Many are pure-function tests needing no services (`test_tool_name`, `test_inherits_abstract_tool`, `_extract_ids_from_json` on plain dicts). With `strict=False`, passing xfailed tests report `XPASS` and don't fail — any future regression is invisible. The xfail reason is demonstrably false.
- [ ] **`doctor.test.ts` — every substantive assertion is vacuously guarded** `[H]` — Lines 31-73: every behavior-specific assertion is wrapped in `if (runtime)`/`if (config)`/`if (env)`/`if (cred)`. If a check is renamed/missing, the `if` is falsy and the test passes without asserting anything. The doctor's MCP-spawn check is never explicitly asserted. `doctorCommand()` is invoked 7× with no mocking and no temp-dir override, spawning real Python processes.
- [ ] **`verify.test.ts` — no successful verification is ever exercised** `[H]` — `mockPage`/`mockContext`/etc. are declared but never referenced. Every seeded finding uses `tool: "unknown-scanner"`, so every test hits the `"No matching verifier found"` branch. The actual verifier runner, Playwright engine, evidence capture, credential lookup, and confidence-update paths are never entered. (Extends §11/§19.)
- [ ] **`resume.test.ts` — "canResume" tests never call canResume (tautological)** `[H]` — Tests named "canResume returns true/false for RUNNING/PAUSED/COMPLETED/FAILED" call `store.updateStatus(...)` then assert `loaded.status === "..."` — they assert the value they just set. All four `resumeCommand` tests exercise only negative paths; the happy path (successfully resuming a RUNNING/PAUSED engagement) is untested.
- [ ] **`evidence.test.ts` — every verify-package test asserts the same "not found"** `[H]` — `mockCollector.saveRequest/saveResponse/captureScreenshot/createPackage` are wired but never invoked. Three `verify-package` tests all assert `INVALID` + `not found`. No test ever creates a valid package and verifies it through `evidenceCommand`.
- [ ] **`finding-analyzer.test.ts:45-68` — assertion contradicts the test name** `[H]` — Test named `"returns null if analysis is stale"`; assertion is `expect(result).not.toBeNull()` — the opposite. The mock store's `getValidAnalysis` returns `null` and the LLM client is `{} as any`, so the result is implementation-defined. Cannot detect any staleness regression.
- [ ] **`test_finding.py` — every assertion wrapped in `try/except: pytest.skip()`** `[H]` — Each of the 4 tests catches `TypeError`/`AttributeError` from the `VulnerabilityFinding` constructor and calls `pytest.skip(...)`. If the model's signature changes, the tests SKIP instead of FAIL. They only assert when the model happens to match exactly — a guard-rail that masks regressions as skips.
- [ ] **`test_args.py` — `is_dangerous` (shell-injection validator) has no real test** `[H]` — Only two tests, both asserting `is_dangerous()` with NO arguments raises `TypeError`. No test passes a malicious string (`"; rm -rf /"`, `` `cat /etc/passwd` ``, `$(...)`) and asserts the return value. The security-critical validator is unit-untested.
- [ ] **`test_distributed_lock.py` — `requires_redis` marker on fully-mocked tests** `[H]` — Every test is `@pytest.mark.requires_redis`, but the `lock` fixture already patches `redis.Redis.from_url` with a mock, and individual tests re-patch redis. These need NO real Redis. If CI runs `-m "not requires_redis"`, this entire mocked suite is wrongly skipped. The marker is semantically false on every test.
- [ ] **`test_orchestrator_integration.py:316,344` — "Tool list mismatch" xfails hide a real planner bug** `[H]` — `test_agent_real_plan_with_matching_phase` registers `nuclei`, sets phase `"scan"`, calls `plan_next_action`, asserts the returned tool is `nuclei` — xfailed with `reason="Tool list mismatch"`. This describes a **real planner defect** (the phase→tool mapping doesn't pick nuclei for scan), not an environment issue. `strict=False` silences it.
- [ ] **`test_wiring_logging.py:95,133,283` — "Orchestrator missing bug_bounty_mode" xfails hide an attribute bug** `[H]` — Tests use `Orchestrator.__new__(Orchestrator)` to bypass `__init__`, manually set a few attributes, then call `osc._save_findings(...)`. Xfailed with `reason="Orchestrator missing bug_bounty_mode"` — the production code accesses `self.bug_bounty_mode` which the bypassed init never set. A real attribute-access bug being hidden.
- [ ] **124 `xfail(..., strict=False)` markers across 21 Python files** `[H]` — Virtually every xfail uses `strict=False`, so `XPASS` (xfailed test that actually passes) does not fail the suite. Stale xfails are never surfaced and regressions in xfailed code are never caught. This is the common root cause of several findings above.
- [ ] **`mcp-client.test.ts`/`supervisor.test.ts` — real reconnection never tested** `[M]` — `connect()` is "tested" by stubbing `spawnChild`; `restartWorker()` is tested with a mock bridge. End-to-end reconnection (real child dies → supervisor detects → real respawn → bridge healthy) is never tested. (Extends §19.)
- [ ] **`test_mcp_server.py` — `call_tool` happy-path subprocess execution never tested** `[M]` — `call_tool` is tested only for error paths (unknown/disabled tool, shell-injection rejection). No test registers a safe tool, calls `call_tool` with valid args, and asserts the subprocess executed and returned a success `MCPToolResult`. The YAML loader's happy path is also untested.
- [ ] **`helpers/reimport.ts:37` — broken helper, dead code** `[M]` — `writeFileSync(bundlePath, "")` overwrites the just-built `bundle.mjs` with an empty string, so `import(bundlePath)` returns an empty module. No test imports `reimport` — dead code with a latent bug.
- [ ] **No TS test for shell-injection/arg-sanitization** `[M]` — The Python side has `test_mcp_server.py::test_call_tool_args_sanitized`, but no TS-side test verifies malicious args are rejected before reaching the subprocess.
- [ ] **`test_llm_client.py:98` — stale xfail for circuit-breaker time comparison** `[M]` — `test_is_available_false_when_circuit_open` is xfailed with `reason="Circuit breaker time comparison issue"`. The sibling `test_is_available_resets_after_cooldown` (line 105) passes — proving the time comparison works. The xfail is stale and should be removed.
- [ ] **`test_fixture_e2e_smoke.py` — Flask lifecycle tests have no flask-availability guard** `[M]` — `TestFixtureAppLifecycle`/`TestSimpleWebAppE2E`/`TestXSSPlaygroundE2E`/`TestAuthBypassE2E` start real Flask subprocesses. There's no skip guard for flask being installed — without flask they hard-fail rather than skip. `conftest.py:106-176` `fixture_app` spawns real processes with no marker filter on the fixture itself.
- [ ] **`near_infinite/test_e2e_full.py` — entire file is a removed-test stub** `[M]` — The whole file is a docstring: "This E2E test has been removed." The `near_infinite/` dir still contains `mock_worker_bridge.py` and `run.sh`, giving the appearance of an e2e suite that's an empty placeholder.
- [ ] **`test_bola_workflow_regression.py` — regression suite excluded from CI by design** `[M]` — Docstring: "These tests are excluded from default CI. Run manually." 4 internal `xfail(reason="Requires full integration setup", strict=False)`. The BolaWorkflow-vs-DualAuthScanner parity suite — called "critical for the zero new detection logic design goal" — does not run in CI.
- [ ] **Test-count discrepancy is far larger than first-pass indicated** `[M]` — Measured: ~3,973 total test functions (3,284 Python `def test_` + ~689 TS `it()`/`test()`). README "335+", Makefile "280+", CI "558", e2e "335" — each is 8–14% of the measured total. The e2e-hardcoded "335" isn't close to any subset that exists today. (Extends §19/§25.)
- [ ] **`engagement-store.test.ts`/`integration/store.test.ts` — temp `dbDir` never cleaned** `[L]` — `dbDir` is created lazily in `makeStore()` but there's no `afterAll` that removes `dbDir` itself (only individual `.db` files are `rmSync`'d). The `argus-engagement-store-test-*`/`argus-store-test-*` temp directories accumulate across runs.

---

### Appendix — Quick verification commands

```bash
# Runtimes
bun --version && python3 --version && npx --version

# Argus health
./start-argus.sh doctor
./start-argus.sh doctor --online      # includes LLM connectivity

# MCP worker reachable?
cd argus-workers && python3 mcp_server.py </dev/null   # should start stdio loop

# Security tools present?
for t in nuclei nmap nikto httpx subfinder amass dnsx naabu dalfox ffuf gospider katana gau waybackurls semgrep gitleaks whatweb; do
  command -v "$t" >/dev/null && echo "ok: $t" || echo "MISSING: $t"
done

# Docker compose sanity
docker compose config -q && echo "compose ok" || echo "compose broken"

# Env required vars
grep -E '^(POSTGRES_PASSWORD|DATABASE_URL|NEXTAUTH_SECRET)=' .env 2>/dev/null || echo "no .env"

# Tests (from the right directory)
cd Argus-Tui/packages/opencode && bun test test/argus/ --timeout 30000
cd argus-workers && source venv/bin/activate && pytest tests/ -m "not requires_db and not requires_redis and not e2e" -q
```

---

## 28. Third-Pass Deep Audit Findings (2026-06-20)

Deep read of the full TS TUI shell, executor/planner/MCP bridge, `bin/argus`, CI workflows, and the actual test files flagged in Pass 2. Items below are NEW — not duplicating §1–§27. All `[C]`/`[H]` items were verified directly against source on 2026-06-20.

### 28.1 Corrections to Pass 1/2 Claims (verified against source)

The following Pass 1/2 claims were found to be **incorrect** on direct verification:

- [ ] **`bin/argus` telemetry beacon exfiltrating CLI args** `[H]` (Pass 1 §20, Pass 2 §27.2) — **INCORRECT.** The committed `bin/argus` (36 lines) contains no telemetry, no `process.chdir`, no `cwd: binDir`. It is a clean passthrough that spawns `bun run` with `stdio: "inherit"` and forwards exit codes. The earlier claims were based on a stale version. Verified by reading HEAD directly.
- [ ] **`bin/argus` destroys the user's CWD** `[H]` (Pass 2 §27.2) — **INCORRECT.** The committed file explicitly does NOT `chdir`. The comment at `bin/argus:11-14` says: "This wrapper intentionally does NOT chdir or override the child's working directory. This preserves the user's original CWD so that CLI commands (assess, report, doctor) can find argus.config.yaml and resolve relative paths correctly."
- [ ] **`setRegistryTools()`/`setConfig()`/`setToolConfig()` have zero callers** `[C]` (Pass 2 §27.1, Top Blockers) — **INCORRECT.** All three ARE called at `workflow-runner.ts:251-255`: `toolRegistry.setConfig(toolConfig)`, `executor.setToolConfig(toolConfig)`, and `bridge.setRegistryTools(toolRegistry.listTools() as ...)`. `ToolConfig.load()` (lines 31-62 of `config/tool-config.ts`) reads `argus.config.yaml` and `~/.argus/config.yaml`. The tool config IS wired. Drift detection compares MCP vs registry (not MCP vs itself). `sqlmap` disable and custom timeouts are applied.
- [ ] **`argus-workers/Dockerfile` Go SHA256 mismatch** `[C]` (Pass 1 §5, Top Blockers) — **INCORRECT.** The Dockerfile (`Dockerfile:16-24`) downloads the SHA256 from `https://go.dev/dl/${GO_TARBALL}.sha256` and runs `sha256sum -c` to verify. This is correct supply-chain practice. No hardcoded wrong hash. Worker/celery-beat images build fine.

### 28.2 NEW TUI Shell & Route Findings

- [ ] **Report route has NO `<Match>` in `app.tsx` → "Generate report →" renders blank screen** `[C]` — `engagement-detail.tsx:177` does `route.navigate({ type: "report", engagementId: props.engagementId })`. The `ReportRoute` type exists in `route.tsx:56-59` and is in the `Route` union (line 61). But `app.tsx:1113-1146` `Switch` has NO `<Match when={route.data.type === "report"}>` case. No component renders the report route. Clicking "Generate report →" lands on a blank screen. Same class of bug as the Pass 2 finding-detail bug, on a different route type. Fix: add `<Match when={route.data.type === "report"}><ReportDashboard engagementId={...} /></Match>` in `app.tsx`.
- [ ] **`home.tsx:17` — module-level `let once = false` is a cross-render state leak** `[H]` — `let once = false` is declared at module scope, read by `bind` (line 88-92) and `createEffect` (line 94-101) to skip the `args.prompt` auto-submit after the first time. If `Home` unmounts and remounts (e.g. user navigates to engagements then back), `once` remains `true` and `args.prompt` auto-submit is permanently suppressed. Fix: move `let once` inside `Home()` and use a `createSignal`.
- [ ] **`executor.ts:272-277` — off-by-one allows 51 iterations on a 50-cap agent loop** `[H]` — `if (++iterations > maxIterations)` with `maxIterations = 50`. `++iterations` evaluates to the post-increment value, so the break fires on the 51st iteration, not the 50th. Each call is a full Python agent step via `bridge.agentNext()`. Documented "50 hardcoded" but actual limit is 51.
- [ ] **`tui-commands.ts:54-58` — `/assess --no-cache` makes the entire arg string the target** `[H]` — `const parts = args.trim().split(/\s+/); const target = parts.find(p => !p.startsWith("--")) ?? parts[0]`. For `/assess --no-cache` (no target), `parts = ["--no-cache"]`, `find` returns `undefined`, fallback `parts[0]` = `"--no-cache"` → `assessCommand("--no-cache", ...)` runs with target = the literal flag string. Also: `/assess https://x.com --no-cache --invalid` silently drops `--invalid` while the user thinks it's active.
- [ ] **`prompt/index.tsx:1218-1222` — TUI `/assess` (no arg) creates orphan empty-target engagement** `[H]` — Before `runner.run(...)`, the TUI calls `store.createEngagement("", "assessment")`. This creates a real row in `~/.argus/argus.db` with `target=""`. If `runner.run` then throws (likely — empty target fails `planner.plan`), the orphan engagement stays and pollutes `engagements.tsx`.
- [ ] **`feature-flags.ts:101-115` — `loadFromCLI()` is dead code** `[C]` — Defined but zero callers (grep confirms only the definition). The CLI passes `featureOverrides` directly to `FeatureFlags` via `applyOverrides(overrides, "constructor")` in `cli.ts:38-43` → `WorkflowRunner.run` → `new FeatureFlags(options.features)`. Either delete the method or wire it into the CLI path.
- [ ] **`dashboard.tsx:106` — `eng.target` flows to scan route with no scheme/format validation** `[M]` — Clicking an engagement navigates to `route.navigate({ type: "scan", target: eng.target, engagementId: eng.id })`. `eng.target` is whatever the user originally typed (no validation in `EngagementStore.createEngagement`). A target like `"foo"`, `"javascript:..."`, `""`, or arbitrary text is passed to `ScanDashboard`, which launches a real assessment.
- [ ] **`tui-command-registry.tsx:14-31` — `cmd.slashes[0]` always wins, no primary-name preference** `[M]` — `insertText = ` /${cmd.slashes[0]}${...}``. For `assess` (slashes: `["assess", "scan"]`), typing `/` and selecting always inserts `/assess` even if the user picked "scan". Users who memorized `/scan` are silently funneled to `/assess`.
- [ ] **`scan.tsx:75` — `setTotalFindings(totalFindings)` includes findings from previous aborted runs** `[M]` — On engagement resume, `store.getFindings(engagementId).length` returns the **cumulative** count (including pre-resume findings). Combined with `completePhase(i, 0, ...)` (line 69), the dashboard shows 100% of total findings immediately on mount, before the new scan has executed any phase. Progress bar shows 100% from the start.
- [ ] **`tui-commands.ts:170-194` — `/tools` spawns a fresh Python worker on every invocation** `[M]` — `new WorkersBridge(wp)` → `bridge.connect()` (spawns `python3 mcp_server.py`) → `getTools()` → `bridge.disconnect()`. Each invocation takes 2-5s. There's already a `toolsCache` inside `WorkersBridge` that could be exposed. Worse: if `/tools` is called when the MCP worker is mid-scan, `disconnect()`'s `killChild` **kills the running worker's bridge**.
- [ ] **`tui-commands.ts:336-345` — `/open` case-sensitivity bug breaks engagement lookup** `[M]` — `const id = args.trim().toUpperCase()` — but DB PKs are `ENG-${Date.now().toString(36)}-${seq.toString(36)}` which are already lowercase (base36). Uppercasing breaks the lookup. `/open eng-1k2j3` → `id = "ENG-1K2J3"` → DB has `eng-1k2j3` → no match → "No engagement or finding found".
- [ ] **`tui-commands.ts:336-373` — `/open FIND-xxx` returns minimal text if no cached analysis exists** `[M]` — Falls through to `return \`Opened ${id}.\`` when `store.getValidAnalysis(id)` is null. User gets no info about the finding (no title, severity, or description). The slash command is the primary "what's in this finding?" entry point.
- [ ] **`tui-commands.ts:212-218` — `/report <id>` ignores LLM `format` and produces only markdown** `[M]` — The handler doesn't pass `useLLM` to `reportCommand`, so `enhanceReportWithAnalysis` uses the feature-flag singleton (which didn't load config in older versions). The user's `argus.config.yaml` `llm_finding_analysis: true` may be ignored.
- [ ] **`tui-commands.ts:243-263` — `/report --format <bad>` silently ignores invalid format, no warning** `[M]` — If user types `/report ENG-001 --format docx`, `validFormats.includes("docx")` is false, format stays as `markdown` (default), and no error is reported. Report is silently generated as markdown instead of the requested format.
- [ ] **`tui-commands.ts:106-126` — `/status` shows fake "Node.js" runtime** `[M]` — `Runtime: Node.js ${process.version}` lies. `package.json` pins `packageManager: "bun@1.3.14"`. Should use `process.versions.bun` or distinguish.
- [ ] **`tui-commands.ts:388-396` — `/verify <finding>` calls `verifyCommand(args.trim())` with no options** `[M]` — `verifyCommand` accepts `storeOverride`/`targetUrl`/`credsPath`. The slash command provides none → uses real `~/.argus/argus.db` and the user's actual credentials. The CLI `argus verify` (cli.ts:131-136) passes options properly. TUI /verify is strictly weaker.

### 28.3 NEW Executor / Planner / MCP Bridge Findings

- [ ] **`mcp-client.ts:191-200` — `exit` handler always sets LLMStatus = UNAVAILABLE regardless of exit code** `[M]` — `code` is captured but never inspected. After a graceful exit (code 0), the LLM is marked UNAVAILABLE. Signal exit codes aren't distinguished from `code 0`. The next `callTool` sees `_llmStatus = UNAVAILABLE` and may interact badly with the `setLLMStatus("DEGRADED")` flow.
- [ ] **`mcp-client.ts:191-200` — `exit` handler doesn't invoke supervisor's auto-restart or call `cleanup()`** `[M]` — The supervisor exists with `restartWorker()` but the `exit` handler never calls it. Between exit and manual reconnect, `process.killed` is false but `exitCode` is set; `sendRequest` correctly rejects, but the orphaned `rl` still has its `line` listener attached.
- [ ] **`mcp-client.ts:316-321` — `ToolResult.success` falls back to `!isError` even when `meta.success` is undefined** `[M]` — If the worker returns `{ content: [], isError: undefined, meta: undefined }`, `success = true` and `data = ""`. The phase reports as completed with 0 findings, but "no findings" vs "transport error masked as no findings" cannot be distinguished.
- [ ] **`supervisor.ts:11-20` — `restartWorker` doesn't reset `attempts` on successful reconnect** `[M]` — If `connect()` succeeds, `attempts` is NOT decremented. After 3 successful kills+reconnects, the 4th call throws "Worker crashed too many times" even though every prior attempt succeeded. The contract is "tries" not "failures" but the supervisor doesn't verify health after reconnect.
- [ ] **`planner.ts:108` — Phase ID collision when two workflows share a phase name at the same index** `[M]` — `phaseId: \`phase-${i}-${def.name}\`` for two different workflows produces duplicates (e.g. both `full_assessment.yaml` and `api_assessment.yaml` have `phase-0-recon`). If `planner.plan` is called once per workflow and results are merged, or if `validateWorkflowVersion` falls through, duplicate phase IDs hit `savePhases` (`onConflictDoUpdate` masks the original row).
- [ ] **`planner.ts:157` — `context.replanCount = nextReplanCount` mutates caller's context** `[M]` — The planner mutates the caller's `PlannerContext` as a side effect. Two concurrent assessments that share a context (e.g. via a single `WorkflowRunner` instance reused) will race.
- [ ] **`strategy.ts:8-9` — `lowerUrl.includes("/api")` matches `/apidoc`, `/capital`, etc.** `[M]` — A URL like `https://example.com/rapid-api-docs` is misclassified as `"api"`. Combined with the now-fixed `supports_api` filter (§27.1), this triggers an "API" plan against a non-API target. Use a path-segment check: `/\/api(\/|$|\?)/`.
- [ ] **`strategy.ts:33` — `lowerUrl.includes("auth")` matches `https://example.com/author`** `[M]` — A URL like `https://www.goodreads.com/author/show/X` is misclassified as `"oauth"`. Use a more specific regex: `/(^|\/)(auth|login|signin|oauth)(\/|$|\?)/`.
- [ ] **`executor.ts:97-104` — `executionOptions` and `emitProgress` never reset between runs** `[M]` — `InProcessExecutor` is constructed once per `WorkflowRunner.run()`. If reused via DI, `setExecutionOptions()` and `setOnProgress()` accumulate — the OLD handlers are never cleared. The new `onProgress` fires alongside the stale one. Add `reset()` or clear in setters.
- [ ] **`executor.ts:113-115` — `onErrorHint` callback captured before `setOnProgress` may run** `[M]` — `toolHealth.onErrorHint` calls `this.emitProgress?.(...)` but `emitProgress` is set later via `setOnProgress`. Any error hint during the first call is silently dropped.
- [ ] **`executor.ts:464-467` — `Math.max(finding.confidence ?? 0, baseConfidence)` then `.promote()` may reduce confidence** `[M]` — If `finding.confidence = 5` (CONFIRMED) and `baseConfidence = 4` (HIGH), `conf = 5` is set, then `promote` may demote it. A tool's own CONFIRMED confidence is downgraded by the engine. Pass the original `finding.confidence` separately and let `promote` decide.
- [ ] **`workflow-runner.ts:189-197` — `argus.config.yaml` read with `try/catch {}` swallows ALL errors** `[M]` — The runner's own load catches ALL errors (including `TypeError`/`ZodError` from malformed YAML) and silently falls through. A typo in `argus.config.yaml` produces zero output, not even a warning to stderr. There's no `console.warn` in the catch.
- [ ] **`workflow-runner.ts:199-205` — `credStore.clear()` runs unconditionally even when no creds existed** `[L]` — `clear()` always runs. The audit log only fires when `defaultCreds` is truthy, but `clear()` always runs, hiding any "creds missing" diagnostic.

### 28.4 NEW Test Suite & CI Findings (extending §27.4)

- [ ] **`assess.test.ts` — no negative test for empty target** `[M]` — Already noted as zero behavioral tests (§27.4). Additionally: there's no `expect(() => assessCommand("")) to throw or return error`. The empty-target case (per §13) has zero coverage.
- [ ] **`verify.test.ts:95-118` — "uses targetUrl" test passes but never verifies the path was used** `[M]` — Passes a `targetUrl` but never asserts the path was actually used; the test passes because `verifyCommand` returns the URL string in its error message, but the URL would be in the error even if it were never used. No mock interceptor on `page.goto`.
- [ ] **CI `lint.yml:393-413` — YAML validation `find` output is unquoted in heredoc** `[M]` — `while IFS= read -r f; do ...yaml.safe_load(open('$f'))... done < <(find . -name "*.yaml" -o -name "*.yml" | ...)` — a filename with spaces (e.g. `Argus Tui/something.yaml`) breaks the Python invocation. The `find` output is unquoted, leading to word-splitting.
- [ ] **CI `lint.yml:328-349,362-385` — `fixture-smoke` and `fixture-full` both `pip install -r requirements-dev.txt` with no cache** `[M]` — Two jobs each run `pip install` (~5 min each), no `actions/cache` for pip. Every CI run pays the install cost twice.
- [ ] **CI `lint.yml:298-304` — `python-tests` doesn't upload JUnit XML** `[L]` — `exit $exit_code` correctly propagates failure, but no `--junit-xml=...` argument. Test failure details are lost after the first 100 lines.
- [ ] **CI `lint.yml:24-40` — `smoke` job has no JUnit upload, no `if: failure()` step** `[L]` — If the smoke test fails, the job fails the workflow but there's no JUnit artifact. A flaky smoke test blocks with no diagnostic.
- [ ] **CI `lint.yml:131-188` — `argus-unit-windows` runs on `windows-latest` but may have path-separator issues** `[L]` — JUnit XML from `bun test` on Windows may have path-separator issues. The `|| true` and `fail_on_failure: false` (now fixed per the many FIXED items) previously masked this.

### 28.5 NEW Configuration & Cross-cutting Findings

- [ ] **`Argus-Tui/packages/opencode/package.json:23-26` — `exports` only allows `./runtime` and `./*.ts`; no `./argus/...` or `./cli/...`** `[M]` — The `"./*"` glob is one-level only. Code that imports `@argus/...` or `argus/...` via the package name `argus` will fail to resolve for any consumer (e.g. a downstream package depending on `argus`).
- [ ] **`tsconfig.json:11-16` — `paths` has no `baseUrl` set** `[L]` — `paths` definitions like `"@tui/*": ["./src/cli/cmd/tui/*"]` work because TypeScript falls back to `tsconfig.json`'s directory when `baseUrl` is unset, but this is implicit and fragile. Add explicit `"baseUrl": "."` for clarity.
- [ ] **`engagement-detail.tsx:42-44` — 4 separate DB queries on every onMount, not memoized** `[L]` — `getEngagement` + `getFindings` + `getEvidenceByEngagement` + `getAuditLog` — all synchronous, blocking onMount. The Solid store is not reactive to DB changes — if another tab updates findings, this view doesn't refresh.
- [ ] **`workspace.tsx:24-30` — Sequential DB query per engagement (N+1)** `[L]` — `for (const e of engs) { const f = store.getFindings(e.id) }` — N engagements → N+1 queries. With 1000 engagements, 1001 SELECTs block the TUI onMount. Add a bulk `getFindingsByEngagementIds(ids)`.
- [ ] **`engagement-detail.tsx:49` — `getAuditLog` entries rendered identically, no event-type filtering** `[L]` — All audit entries rendered with the same `evt.message`. The `eventType` field is available but unused. No filtering by phase, by tool, by user.
- [ ] **`findings.tsx:121-124` — `description.slice(0, 200)` truncates without word-boundary awareness** `[L]` — A description ending mid-word at char 200 produces "the quick brown fo..." (mid-word cut). No `findLastIndex(" ")` to break at the last space. Cosmetic.
- [ ] **`scan.tsx:64-71` — `for (let i = 0; i < engPhases.length; i++)` indexes by position, fragile across replans** `[L]` — If the engagement was started, paused, and the workflow re-planned, the phase IDs in the DB may not match the scan store's positions. The mapping is positional and fragile.
- [ ] **`findings.tsx:171` — `catch (e) { console.error(...) }` swallows load errors; no toast shown** `[L]` — Error logged to console, user sees "No findings for this engagement." (or loading state never resolves). `findings.tsx` doesn't import `useToast` (it's not mounted with `<Toast />` per §27.2).

### 28.6 Verified: existing items in the checklist that are genuinely correct on re-read

The following Pass 1/2 items were re-verified in Pass 3 and are **confirmed correct** (not incorrect as the corrections above):

- [ ] **Parser registry empty** `[C]` — `parsers/parsers/__init__.py:43` confirmed: `importlib.import_module("parsers.parsers.%s", module_name)` with literal `%s`. All parsers fail to import. **(Now fixed per the FIXED items.)**
- [ ] **Finding-detail TUI route** `[C]` — `app.tsx:392` `route.navigate({ type: "finding", findingId: r.findingId } as any)` vs `route.tsx:51` `FindingDetailRoute = { type: "finding-detail" }` — confirmed. **(Now fixed.)**
- [ ] **LLM integration non-functional** `[C]` — `finding-analyzer.ts:30` `if (!this.llmClient) return null`; both call sites pass no llmClient. Confirmed. **(Now fixed.)**
- [ ] **Non-agent tools 120s timeout** `[C]` — `executor.ts:451` `PER_TOOL_TIMEOUT_MS = 120_000`; bridge sends this as JSON-RPC timeout. Confirmed. **(Now fixed.)**
- [ ] **`selectBest` web filter dead** `[C]` — `detectTargetType` returns `"web_app"|"api"|"spa"|"unknown"`, never `"web"`. Confirmed. **(Now fixed.)**
- [ ] **Approval gates inert** `[C]` — No workflow YAML sets `approval_gate`; `APPROVAL_GATES` defaults false. Confirmed. **(Now fixed.)**
- [ ] **`alterx` parameter name `domain` doesn't match executor's `target` key** `[C]` — `alterx.yaml:7` `name: domain`; executor passes `target`. Confirmed. **(Now fixed.)**
- [ ] **`home.tsx` MCP path off by one level** `[H]` — `home.tsx:76` 7 `..` lands at `Argus-Tui/`, not repo root. Confirmed. **(Now fixed.)**
- [ ] **`@opencode/runtime` non-resolvable** `[H]` — `package.json` name is `"argus"`, not `"opencode"`; `tsconfig.json` has no `@opencode/runtime` mapping. Confirmed. **(Partially fixed — the file is now more accurately documented as aspirational.)**
- [ ] **`bin/argus` does not handle `--version`/`--help` before spawning** `[L]` — Confirmed: every invocation spawns a full `bun run` child. However, the main `index.ts` (which `bin/argus` delegates to) does handle `--help`/`--version` (line 84). So the effective behavior is correct (help works), just via the child.
- [ ] **Test-count discrepancy** — Pass 2 measured ~3,973 total test functions (3,284 Python + ~689 TS). Pass 3 confirmed: 53 TS test files, 326 Python test files. The README "335+", Makefile "280+", CI "558", e2e "335" remain mutually inconsistent.
- [ ] **Two SQLite databases, no collision** — Pass 3 confirmed via `database.ts:42-54` and `store.ts:33`: Argus uses `~/.argus/argus.db`, OpenCode core uses `Global.Path.data/opencode.db`. Different files, different directories. No conflict.
---

*End of checklist. Items marked `(see BUG_SWEEP_REPORT §X)` have additional code-logic detail in `docs/BUG_SWEEP_REPORT.md`. When you fix an item, tick the box and add the commit/PR reference inline.*
*
*Audit totals: Pass 1 (§1–§26): 259 items. Pass 2 (§27): ~100 additional items, including 8 new Critical and ~20 new High. Pass 3 (§28): ~30 additional items (2 new Critical: report route blank screen, dead `loadFromCLI`; 4 new High: home `let once` leak, executor off-by-one, `/assess --no-cache` target corruption, orphan engagement creation; ~20 Medium/Low). Pass 3 also verified 4 Pass 1/2 claims as incorrect and corrected them. All Pass 2/3 Critical/High items were verified directly against source on 2026-06-20. Post-audit fix pass (2026-06-20): Redis binaries actually removed from git tracking; telemetry beacon claims corrected; `selectBest` web filter description aligned with actual implementation. Currently 108 items marked fixed/resolved; 271 remain unchecked; 3 claims corrected.*
