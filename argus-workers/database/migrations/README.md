# Database Migrations

## Migration Files

- `001_base_schema.sql` — Core tables: engagements, findings, feature_flags, user_settings
- `002_audit_logging.sql` — Audit logging: audit_log, performance_log
- `003_webhooks_loop_budgets.sql` — Webhook dispatch: webhooks, loop_budgets
- `004_*`+ — Higher-numbered migrations (these exist as separate files in this directory)

## How to Apply

Migrations are applied automatically by `run_migrations()` in the database connection module.
Base schema (migrations 001-003) is also initialized via `argus-workers/database/init/01-schema.sql`
and `argus-workers/database/init/02-audit.sql` which are mounted as Docker entrypoint scripts.

## Migration Convention

- Each file is numbered sequentially (001, 002, 003, ...)
- Files contain idempotent SQL (CREATE IF NOT EXISTS)
- Migrations are applied in numerical order
- Down migrations are commented out at the bottom of each file
