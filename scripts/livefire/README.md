# Argus Live-Fire Validation Suite

End-to-end validation tools for running Argus against deliberately vulnerable targets (Juice Shop, DVWA) to observe emergent behavior, verify finding quality, and measure resource usage.

## Quick Start

```bash
# 1. Set up infrastructure
docker compose up -d postgres redis
docker compose -f docker-compose.yml -f docker-compose.override.yml up -d worker

# 2. Start the target
docker compose --profile e2e up -d juice-shop

# 3. Seed the engagement in the database
docker compose exec -T postgres psql -U argus_user -d argus_pentest <<'SQL'
INSERT INTO engagements (
  id, org_id, target, target_url, status, scan_type, workflow, workflow_version,
  authorization_proof, authorized_scope, created_by, metadata
) VALUES (
  'a1b2c3d4-1111-4000-8000-000000000001',
  '00000000-0000-0000-0000-000000000001',
  'http://127.0.0.1:3001', 'http://127.0.0.1:3001',
  'created', 'url', 'default', 1,
  '{"proof_type":"livefire"}',
  '{"domains":["127.0.0.1:3001","localhost:3001"],"ipRanges":[]}',
  'livefire-operator',
  '{"purpose":"livefire_validation"}'
);
SQL

# 4. Run the validation
bash scripts/livefire/run-livefire.sh

# 5. Review the results
less livefire-runs/livefire-juice-shop-*/post-mortem.txt
```

## Files

| File | Purpose |
|------|---------|
| `run-livefire.sh` | Main orchestration script — runs full validation cycle |
| `harness_config.py` | Validates `AGGRESSIVENESS`/`SCAN_MODE`/`REQUIRE_SWARM`/`REQUIRED_SPECIALISTS` before dispatch |
| `assert-livefire.py` | Applies the criteria below to the run's own artifacts and writes `verdict.json` |
| `lab-answer-manifest.json` | The lab's answers, controls and sentinel — harness-side only |
| `test-fixture-auth-bypass.py` | Standalone contract check for the resettable lab (no database or worker) |
| `job-recon.json` | Sample engagement payload template (the runner builds its own; editing this changes nothing) |
| `post-mortem.sql` | SQL analysis queries for post-run database inspection |
| `README.md` | This file |

## Running without Docker

Docker is only how these instructions suggest bringing the infrastructure up; nothing in the harness
requires containers. On a host that already runs Postgres and Redis natively:

```bash
# 1. Start the Celery worker (its own .env supplies DATABASE_URL and the LLM key)
cd argus-workers
export REDIS_URL=redis://localhost:6379
# A loopback target is an internal/SSRF target to the worker, which refuses to
# scan it without this opt-in — the run then completes green and finds nothing.
export ARGUS_ALLOW_INTERNAL_TARGETS=1
# macOS only: Celery's prefork pool aborts in its children
# (objc_initializeAfterForkError). The solo pool avoids the fork entirely; the
# alternative is OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES with the default pool.
nohup venv/bin/celery -A celery_app worker --loglevel=info --pool=solo \
  > /tmp/livefire-worker.log 2>&1 &
WORKER_PID=$!
cd ..

# 2. Seed the engagement once (org_id and created_by need existing rows)
psql -h localhost -U argus_user -d argus_pentest -c "\
INSERT INTO engagements (id, org_id, created_by, target_url, authorization_proof, authorized_scope) \
SELECT 'a1b2c3d4-1111-4000-8000-000000000001', o.id, u.id, 'http://127.0.0.1:55693', \
       '{\"proof_type\":\"livefire\"}', '{\"domains\":[\"127.0.0.1:55693\"]}' \
FROM organizations o, users u WHERE o.id = '00000000-0000-0000-0000-000000000001' LIMIT 1;"

# 3. Run — scope follows TARGET_URL unless ALLOWED_TARGETS is set
TARGET_URL=http://127.0.0.1:55693 TARGET_LABEL=fixture \
PYTHON=argus-workers/venv/bin/python \
PSQL=/opt/local/lib/postgresql15/bin/psql \
WORKER_LOG=/tmp/livefire-worker.log WORKER_PID=$WORKER_PID \
bash scripts/livefire/run-livefire.sh
```

The worker must consume the phase queues (`recon`, `scan`, `analyze`, `report`) — `celery_app.py`
declares them, so a plain `celery -A celery_app worker` picks them up, and `scripts/mac/start-argus.sh`
passes them explicitly with `-Q`.

On a host without Docker there is no `docker-entrypoint-initdb.d`, so the migration runner applies `database/init/01-schema.sql` and `02-audit.sql` itself when the database has no `organizations` table; `python -m database.migrations.runner` is therefore enough to build a fresh database, and a failing migration exits non-zero with a `failed` row instead of being counted as applied. If Redis requires a password, put it in `REDIS_URL` (`redis://:password@host:6379/0`) so the worker, the harness and `argus doctor` all authenticate.

`PSQL` is how the harness reaches the database (`psql …` or `docker compose exec …`); `WORKER_LOG`
and `WORKER_PID` let it read the worker's events and sample its memory, which Docker would otherwise
provide. The run ends with a pass/fail verdict in `${LOG_DIR}/verdict.json` and exits non-zero when a
criterion fails; the first run for a label stores `livefire-runs/baseline-<label>.json`, and later
runs must stay within ±50% of it.

Each run creates a **fresh engagement** unless you pass `ENGAGEMENT_ID` explicitly, and it never
deletes findings. The effective options, scope, feature flags and IDs are saved as
`${LOG_DIR}/effective-config.json`, so a verdict can be reproduced from the artifact rather than
from the caller's shell history. With `LAB_RESET=1` the runner also calls the lab's `POST /__lab/reset`
and saves the run marker in `${LOG_DIR}/lab-reset.json`.

The "What Good Looks Like" numbers below describe Juice Shop. Runs with another `TARGET_LABEL`
assert the target-independent criteria (pipeline completed, findings persisted, scope held, no orphan
scanners, worker under budget, at least one engine-chosen tool) and diff against that label's baseline
rather than against Juice Shop's ranges.

## What It Tests

The live-fire run exercises and measures:

- **Recon phase**: Tech stack detection, endpoint discovery, parameter discovery
- **Swarm agent activation**: explicit opt-in (`REQUIRE_SWARM=1 AGGRESSIVENESS=high`); the
  default stays moderate and does not require the swarm
- **LLM agent decision quality**: Tool selection, ordering, retry behavior
- **Deterministic fallback**: How often the agent fails and falls back
- **Finding verification**: HTTP-based verification of SQLi, XSS, Open Redirect findings
- **Resource usage**: Worker memory, subprocess orphan detection, CPU usage
- **Scope validation**: That SSRF/internal targets are correctly blocked
- **End-to-end pipeline**: That recon → scan → analyze → report chain completes

## Swarm opt-in and proof

The default payload is still `moderate`/`standard`; nothing about the swarm is implicit. The
runner validates these options with `harness_config.py` **before dispatch**, so a contradictory
combination stops the run instead of producing a green verdict:

| Variable | Default | Meaning |
|----------|---------|---------|
| `AGGRESSIVENESS` | `moderate` | `low`, `moderate`, `high`, `extreme`; the specialist gate needs `high` or `extreme` |
| `SCAN_MODE` | `standard` | `standard`, `agent`, `swarm`, `deterministic` |
| `REQUIRE_SWARM` | `0` | Require the specialist proof below |
| `REQUIRED_SPECIALISTS` | all three when required | `idor,auth,api` (requires `REQUIRE_SWARM=1`) |

With `REQUIRE_SWARM=1`, `assert-livefire.py` reads the structured `[SWARM_EVENT]` JSON lines for
this engagement (saved as `${LOG_DIR}/swarm-events.jsonl`) and fails unless **each** required
specialist:

1. activates (`agent_started`),
2. actually executes at least one tool successfully (`tool_executed`, `status=success`),
3. shows provenance — a tool it selected is the tool that executed,
4. completes with `status=completed` and no failed tool/error/timeout event.

`Swarm: no specialists activated` is a sentence, not evidence: it now produces an explicit
failing criterion. A completion with errors, a timeout, or a missing event also fails. The
specialist suites are hardcoded, so their selection is labelled `deterministic`; the verdict never
claims an LLM chose those tools.

### The resettable lab

`argus-workers/test_fixtures/auth-bypass/app.py` is the lab: a linked landing/login page, an API
description at `/api/docs`, two synthetic users, per-run markers, a vulnerable ownership check
(`/api/data/<id>`) with a secure twin (`/api/secure/data/<id>`), an admin profile and users list,
and a debug-header flag. The answer manifest lives in this directory, never in the target.

```bash
# Terminal 1: start the lab
cd argus-workers/test_fixtures/auth-bypass
LAB_RUN_MARKER=my-run LAB_TEST_MODE=1 ../../venv/bin/python app.py 18080

# Terminal 2: prove the lab itself
argus-workers/venv/bin/python scripts/livefire/test-fixture-auth-bypass.py

# Terminal 3: full live-fire run that must prove the swarm
TARGET_URL=http://127.0.0.1:18080 TARGET_LABEL=lab LAB_RESET=1 \
AGGRESSIVENESS=high SCAN_MODE=swarm REQUIRE_SWARM=1 \
PYTHON=argus-workers/venv/bin/python \
WORKER_LOG=/tmp/livefire-worker.log \
bash scripts/livefire/run-livefire.sh
```

A loopback target still needs `ARGUS_ALLOW_INTERNAL_TARGETS=1` on the worker. Local scope is the
normal allowlist plus that opt-in; the specialists now send every target they add (recon endpoints,
peer discoveries and raw endpoint fallbacks) through the same `authorize_target` decision, so scope
cannot be bypassed by appending raw recon data.

## Expected Timings

| Phase | Duration | Notes |
|-------|----------|-------|
| Recon | 3-8 min | Crawling, tech detection, parameter discovery |
| Scan | 5-15 min | Agent-driven tool selection + deterministic safety net |
| Analysis | 2-5 min | LLM evaluation, PoC generation, chain exploits |
| Report | 1-3 min | Report generation, optional compliance reports |
| **Total** | **11-31 min** | Varies by target size and aggressiveness |

## What Good Looks Like

- **Swarm**: 3/3 agents activate (IDOR, Auth, API)
- **Findings**: 10-25 total findings, at least 2 CRITICAL or HIGH
- **Agent fallback rate**: 0% (agent succeeds on all targets)
- **Verification**: >30% of HIGH+ findings confirmed
- **Orphan processes**: 0 post-scan
- **Worker memory**: <500 MB peak
- **Scope violations**: 0

## Custom Target

```bash
TARGET_URL=https://staging.example.com \
ENGAGEMENT_ID=b2c3d4e5-2222-4000-8000-000000000002 \
TARGET_LABEL=staging \
bash scripts/livefire/run-livefire.sh
```

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Worker can't reach target | Not in host network mode | `docker compose -f docker-compose.yml -f docker-compose.override.yml up -d worker` |
| No swarm log lines | Default payload is `moderate`; specialist gate requires `high`/`extreme` | Set `AGGRESSIVENESS=high REQUIRE_SWARM=1`; invalid combinations fail before dispatch |
| Swarm criterion fails | A required specialist did not activate, execute, prove provenance or complete cleanly | Read `${LOG_DIR}/swarm-events.jsonl`; do not relax the criterion |
| "No specialists activated" | Swarm was entered but recon has insufficient API/auth signals | Inspect `[SWARM_METRICS].inactive_agents` and the saved recon context |
| Engagement stuck in 'scanning' | Tool hanging | Check `HARD_TIMEOUT_SECONDS` in config; toolbar may need timeout adjustment |
| 0 findings at completion | All findings filtered or empty | Check `scope.mode` — if `allowlist` with empty `allowed_targets`, everything is blocked |
| LLM agent returns no results | LLM API key missing | Check `LLM_API_KEY` env var on worker |
