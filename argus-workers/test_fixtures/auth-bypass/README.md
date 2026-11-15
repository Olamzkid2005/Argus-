# Argus ownership lab

A small, resettable target for Stage 7 discovery/verification. It is still a
fixture, not a realistic application: every endpoint exists to prove one
behaviour, and the answer manifest is kept in the harness
(`scripts/livefire/lab-answer-manifest.json`), never served here.

## Run

```bash
LAB_RUN_MARKER=my-run LAB_TEST_MODE=1 ../../venv/bin/python app.py 18080
```

`LAB_RUN_MARKER` seeds the per-run marker; `LAB_TEST_MODE=1` (the default)
enables the reset and request-log endpoints.

## What it exposes

| Endpoint | Behaviour |
|----------|-----------|
| `GET /` | Landing page: login form, API links, XSS-fixture link, out-of-scope sentinel |
| `GET/POST /login` | Form or JSON login; predictable passwords (`user1/welcome1`, `user2/welcome2`, `admin/password123`) |
| `GET /api/docs` | Discoverable API description with resources and auth hints |
| `GET /api/me` | Authenticated identity |
| `GET /api/data/<id>` | **Vulnerable**: any logged-in user reads any owner's resource |
| `GET /api/secure/data/<id>` | **Secure twin**: owner or admin only (403 otherwise) |
| `GET /admin/profile` | Admin data with no role check |
| `GET /admin/users` | Credential list with no access control |
| `GET /flag` | Auth bypass with `X-Debug-Token: argus-bypass-2026` |
| `POST /__lab/reset` | Test-only: reset resources, rotate marker, clear the request log |
| `GET /__lab/requests` | Test-only: target-side request log (method, path, status, identity, marker) |

Every response carries the active `marker`, so a finding can be tied to the run
that produced it.

## Verify it

```bash
argus-workers/venv/bin/python scripts/livefire/test-fixture-auth-bypass.py
argus-workers/venv/bin/python -m pytest argus-workers/tests/test_lab_fixture_contract.py -q
```

The XSS fixture is linked from `/` through `XSS_FIXTURE_URL` (default
`http://127.0.0.1:18766`) rather than copied here, so the planner can discover it
without reading its source.
