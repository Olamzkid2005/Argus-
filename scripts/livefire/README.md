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
| `job-recon.json` | Sample engagement payload template |
| `post-mortem.sql` | SQL analysis queries for post-run database inspection |
| `README.md` | This file |

## What It Tests

The live-fire run exercises and measures:

- **Recon phase**: Tech stack detection, endpoint discovery, parameter discovery
- **Swarm agent activation**: Which specialist agents activate and why
- **LLM agent decision quality**: Tool selection, ordering, retry behavior
- **Deterministic fallback**: How often the agent fails and falls back
- **Finding verification**: HTTP-based verification of SQLi, XSS, Open Redirect findings
- **Resource usage**: Worker memory, subprocess orphan detection, CPU usage
- **Scope validation**: That SSRF/internal targets are correctly blocked
- **End-to-end pipeline**: That recon → scan → analyze → report chain completes

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
| "No specialists activated" | Recon missed API/auth signals | Check `recon_context` in Redis — verify target has API endpoints |
| Engagement stuck in 'scanning' | Tool hanging | Check `HARD_TIMEOUT_SECONDS` in config; toolbar may need timeout adjustment |
| 0 findings at completion | All findings filtered or empty | Check `scope.mode` — if `allowlist` with empty `allowed_targets`, everything is blocked |
| LLM agent returns no results | LLM API key missing | Check `LLM_API_KEY` env var on worker |
