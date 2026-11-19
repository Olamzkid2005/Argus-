# Engagement: Acme Logistics — Expense Portal

A self-contained penetration-test scenario for Argus. Everything here is
fictional: the company, the staff, the credentials in `dotenv.txt`, and the
hostnames. The application is deliberately vulnerable and binds to loopback
only, so the drill can be run without touching any real system.

## Brief

Acme Logistics' sales team files receipts through an "Expense Portal" built by a
contractor in 2019. The security lead has written authorization to test the
portal before it is exposed to the wider intranet. The engagement letter asks
for black-box coverage of the public surface:

| Target | `http://127.0.0.1:8080` |
| --- | --- |
| Window | One assessment run, business hours |
| Credentials | None supplied (black box) |
| Rules of engagement | Read-only; no destructive actions; stop at proof |
| Out of scope | The host itself (`127.0.0.1` OS), third-party services |

## Known-suspicious surface (for the operator, not the scanner)

The portal is a small Flask-shaped service with the mistakes such a service
really ships:

- `POST /login` builds SQL by string concatenation (`' OR '1'='1`)
- `GET /admin` renders the admin panel without any session check
- `GET /api/expenses?id=N` returns any employee's expense (IDOR)
- `GET /search?q=` reflects the term unescaped (reflected XSS)
- `GET /redirect?next=` honours any URL (open redirect)
- `GET /api/users` reflects any `Origin` with credentials allowed
- `GET /.env` serves the production environment file
- No `Content-Security-Policy`, `X-Frame-Options`, `Strict-Transport-Security`
  or `X-Content-Type-Options`; the session cookie is neither `HttpOnly` nor
  `Secure`; `Server`/`X-Powered-By` disclose the stack.

## Running the drill

```bash
# 1. Start the target (the worker virtualenv already has Flask-free stdlib deps)
argus-workers/venv/bin/python scenarios/acme-portal/app.py --port 8080 &

# 2. Run the assessment from this directory so argus.config.yaml scopes it.
#    ARGUS_ALLOW_INTERNAL_TARGETS=1 is the worker's explicit opt-in for a lab
#    or intranet target: an internal address stays refused without it, even
#    when the allowlist names it. REDIS_URL is required by autonomous mode's
#    distributed engagement lock.
cd scenarios/acme-portal
export REDIS_URL=redis://127.0.0.1:6379/0
export ARGUS_ALLOW_INTERNAL_TARGETS=1
bun run ../../Argus-Tui/packages/opencode/src/argus/main.ts assess \
  http://127.0.0.1:8080 --deterministic --autonomous --verbose --no-cache

# 3. Read the report the run wrote, or re-render it for the engagement id
bun run ../../Argus-Tui/packages/opencode/src/argus/main.ts report <ENGAGEMENT_ID>
```

Optional: the interactive TUI (`./start-argus.sh tui`) drives the same pipeline
and shows the phase transcript live.

## What "done" looks like

The run finishes with a report listing the weaknesses above, evidence artifacts
for the confirmed ones, and an explicit statement of any coverage it had to
degrade (for example a phase skipped because no scanner binary is installed on
this host). A run that silently claims full coverage is a bug in Argus, not a
clean portal.
