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
| `assert-livefire.py` | Applies the criteria below to the run's own artifacts and writes `verdict.json` |
| `job-recon.json` | Sample engagement payload template |
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

`PSQL` is how the harness reaches the database (`psql …` or `docker compose exec …`); `WORKER_LOG`
and `WORKER_PID` let it read the worker's events and sample its memory, which Docker would otherwise
provide. The run ends with a pass/fail verdict in `${LOG_DIR}/verdict.json` and exits non-zero when a
criterion fails; the first run for a label stores `livefire-runs/baseline-<label>.json`, and later
runs must stay within ±50% of it.

The "What Good Looks Like" numbers below describe Juice Shop. Runs with another `TARGET_LABEL`
assert the target-independent criteria (pipeline completed, findings persisted, scope held, no orphan
scanners, worker under budget, at least one engine-chosen tool) and diff against that label's baseline
rather than against Juice Shop's ranges.

## What It Tests

The live-fire run exercises and measures:

- **Recon phase**: Tech stack detection, endpoint discovery, parameter discovery
- **Swarm agent activation**: Logged when reached, but **not exercised by the default payload**
  (`aggressiveness: "moderate"` skips the `high`/`extreme` specialist gate)
- **LLM agent decision quality**: Tool selection, ordering, retry behavior
- **Deterministic fallback**: How often the agent fails and falls back
- **Finding verification**: HTTP-based verification of SQLi, XSS, Open Redirect findings
- **Resource usage**: Worker memory, subprocess orphan detection, CPU usage
- **Scope validation**: That SSRF/internal targets are correctly blocked
- **End-to-end pipeline**: That recon → scan → analyze → report chain completes

## Swarm reachability — investigation (2026-09-30)

**The stock harness does not exercise the specialist swarm.** `run-livefire.sh::dispatch_recon`
hardcodes `aggressiveness: "moderate"` and `scan_mode: "standard"`. There is no harness environment
knob for either field; exporting `AGGRESSIVENESS=high` or `SCAN_MODE=swarm` currently changes nothing.
`job-recon.json` is a sample, not the input read by the runner, so editing it changes nothing either.

The worker path is wired:

`JobMessage.to_celery_args()` → `tasks.recon.run_recon` → `tasks.scan.run_scan` →
`Orchestrator.run_scan` → `_run_scan_with_fallback` → `_run_swarm_specialists`.

Its prerequisites are:

1. Agent mode enabled and scan mode not `deterministic`. `standard`, `agent`, and `swarm` all use
   the **same agent-first route**; `scan_mode="swarm"` is not a separate dispatch branch.
2. The agent-first/safety-net path completes without an exception. The full deterministic exception
   fallback does not run specialists.
3. Aggressiveness is **`high` or `extreme`**, recon context exists, the
   `swarm_specialists` flag is enabled (default `True`; worker override
   `ARGUS_FF_SWARM_SPECIALISTS=0` disables it), and the worker's LLM client is available.
4. Recon signals activate each specialist independently. IDOR needs parameter/API signals (or a
   sufficiently large dynamic crawl); Auth needs login/auth/API signals (or a large dynamic crawl);
   API needs stronger evidence, such as `has_api=True` with at least two API endpoints.

**Evidence from `livefire-fixture-20260930-221601`:** `dispatch.log:5` shows `moderate` was sent
unchanged. `worker.log:850` records zero live/API/auth endpoints, no parameter-bearing URLs,
`has_api=False`, `has_login_page=False`, and one crawled URL. `worker.log:906` confirms the
agent-first route, and `worker.log:1025` confirms the safety net received `aggressiveness=moderate`.
The first gate therefore skips the swarm before specialist activation is evaluated. Even changing
only aggressiveness would leave **0/3 specialists active** for that saved recon context.

**Measurement caveat:** `assert-livefire.py::swarm_events` counts `Swarm:` log lines, not specialists.
`Swarm: no specialists activated` would count as one event. The verdict has no swarm activation
criterion, so PASS (9/9) proves neither swarm reachability nor 3/3 activation. Use the structured
`[SWARM_METRICS]` payload's `activated_agents`, `inactive_agents`, per-agent tools/errors/timeouts,
and completion events for real proof. Swarm tool suites are hardcoded; their `was_fallback=False`
decision rows alone do not prove an LLM chose those tools.

**Local-target caveat:** `SpecialistAgent._get_targets()` and peer-target filtering reject internal
addresses unconditionally, without reading `ARGUS_ALLOW_INTERNAL_TARGETS`. IDOR can activate but
receive zero targets on loopback. Auth/API also append raw recon endpoints or fall back to
`target_url` after `_get_targets()`, so the layers do not implement one consistent local opt-in.
Do not weaken scope checks or claim a local swarm scan works based only on activation logs.

**Verified in isolated tests:** `test_swarm_wiring.py` exercises the real swarm activation and
parallel dispatch with specialist bodies stubbed: `high`/`extreme` plus two API endpoints activates
IDOR/Auth/API; the saved fixture signals activate none. It also pins the shared scan-mode route and
the ignored internal-target opt-in. These are routing/activation tests, **not a live specialist scan**.

**Next implementation:** add an explicit harness aggressiveness opt-in (keep the moderate default),
record/assert per-specialist activation and completion, and align authorized local-target handling
across the specialist paths. Then run against a scoped target whose recon actually discovers
API/auth signals. Raising aggressiveness alone, or merely selecting `scan_mode="swarm"`, is not proof.

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
| No swarm log lines | Default payload is `moderate`; specialist gate requires `high`/`extreme` | See swarm reachability above; the runner has no aggressiveness override yet |
| "No specialists activated" | Swarm was entered but recon has insufficient API/auth signals | Inspect `[SWARM_METRICS].inactive_agents` and the saved recon context |
| Engagement stuck in 'scanning' | Tool hanging | Check `HARD_TIMEOUT_SECONDS` in config; toolbar may need timeout adjustment |
| 0 findings at completion | All findings filtered or empty | Check `scope.mode` — if `allowlist` with empty `allowed_targets`, everything is blocked |
| LLM agent returns no results | LLM API key missing | Check `LLM_API_KEY` env var on worker |
